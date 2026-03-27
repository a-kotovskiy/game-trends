#!/usr/bin/env python3
"""Обновляет только hype.json + meta.json"""
import subprocess, json, sys, os
from datetime import datetime
import zoneinfo
MSK = zoneinfo.ZoneInfo("Europe/Moscow")

WORKSPACE = "/Users/andrey/.openclaw/workspace"
DASHBOARD = f"{WORKSPACE}/dashboard"
SCRIPTS = f"{WORKSPACE}/scripts"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

def get_tiktok_hype():
    log("Собираю TikTok FYP хайп...")
    try:
        subprocess.run(
            ["python3", f"{SCRIPTS}/fetch_tiktok_foryou.py"],
            timeout=120, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )
        tmp = "/tmp/tiktok_foryou.json"
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = json.load(f)
            log(f"TikTok FYP: {len(data)}")
            return data
    except Exception as e:
        log(f"TikTok FYP: ошибка - {e}")
    return []

def get_viral_trends():
    log("Собираю вирусные тренды...")
    try:
        subprocess.run(
            ["python3", f"{SCRIPTS}/fetch_viral_videos.py"],
            timeout=180, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )
        tmp = "/tmp/viral_videos.json"
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = json.load(f)
            log(f"Вирусные тренды: {len(data)}")
            return data
    except Exception as e:
        log(f"Вирусные тренды: ошибка - {e}")
    return []

def get_validated_hype():
    log("Запускаю перекрёстную проверку хайпа...")
    try:
        subprocess.run(
            ["python3", f"{SCRIPTS}/validate_hype.py"],
            timeout=300, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )
        tmp = "/tmp/hype_validated.json"
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = json.load(f)
            log(f"Валидированный хайп: {len(data)} подтверждённых")
            return data
    except Exception as e:
        log(f"Валидация хайпа: ошибка - {e}")
    return []

def get_tiktok_playwright():
    log("TikTok через Playwright...")
    try:
        subprocess.run(
            ["python3", f"{SCRIPTS}/fetch_tiktok_playwright.py"],
            timeout=300, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )
        tmp = "/tmp/tiktok_playwright.json"
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = json.load(f)
            log(f"TikTok Playwright: {len(data)} хайп-видео")
            return data
    except Exception as e:
        log(f"TikTok Playwright: ошибка - {e}")
    return []

def get_tg_signals():
    log("Сигналы из Telegram каналов...")
    try:
        subprocess.run(
            ["python3", f"{SCRIPTS}/fetch_tg_signals.py"],
            timeout=120, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )
        tmp = "/tmp/tg_signals.json"
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = json.load(f)
            log(f"TG сигналы: {len(data)} тем")
            return data
    except Exception as e:
        log(f"TG сигналы: ошибка - {e}")
    return []

def get_channel_hype():
    log("Мониторинг gaming-каналов...")
    try:
        result = subprocess.run(
            ["python3", f"{SCRIPTS}/monitor_channels.py"],
            timeout=600, capture_output=True
        )
        tmp = "/tmp/channel_hype.json"
        if os.path.exists(tmp):
            with open(tmp) as f:
                data = json.load(f)
            log(f"Хайп каналов: {len(data)} видео")
            return data
    except Exception as e:
        log(f"Мониторинг каналов: ошибка - {e}")
    return []

viral_trends = get_viral_trends()
tiktok_hype = get_tiktok_hype()
tiktok_playwright_data = get_tiktok_playwright()
channel_hype = get_channel_hype()
hype_validated = get_validated_hype()
tg_signals = get_tg_signals()

# Объединяем (дедупликация по video id)
seen_ids = set()
all_hype = []
for v in tiktok_hype + channel_hype + [v for v in viral_trends if v.get('source') != 'google_trends']:
    vid_id = v.get('id') or v.get('url', '')
    if vid_id not in seen_ids:
        seen_ids.add(vid_id)
        all_hype.append(v)
all_hype.sort(key=lambda x: x.get('vpd', 0), reverse=True)
google_trends = [v for v in viral_trends if v.get('source') == 'google_trends']

# Сохраняем hype.json
hype_data = {
    "viral_trends": all_hype[:30],
    "google_trends": google_trends,
    "hype_validated": hype_validated,
    "tiktok": tiktok_playwright_data[:30],
    "tg_signals": tg_signals,
}

path = f"{DASHBOARD}/hype.json"
if all_hype or hype_validated:
    with open(path, "w") as f:
        json.dump(hype_data, f, ensure_ascii=False, indent=2)
    log(f"hype.json: {len(all_hype[:30])} трендов, {len(hype_validated)} валидированных")
elif os.path.exists(path):
    log("hype.json: пустой результат, сохраняем старые данные")

# Обновляем meta.json
meta_path = f"{DASHBOARD}/meta.json"
meta = {}
if os.path.exists(meta_path):
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except: pass

now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M МСК")
meta["hype_count"] = len(all_hype[:30])
meta["google_trends_count"] = len(google_trends)
meta["hype_validated_count"] = len(hype_validated)
meta["hype_updated"] = now
meta["updated"] = now
with open(meta_path, "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

log("✅ Хайп обновлён")
