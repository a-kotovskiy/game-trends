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

viral_trends = get_viral_trends()
tiktok_hype = get_tiktok_hype()
hype_validated = get_validated_hype()

# Объединяем
all_hype = tiktok_hype + [v for v in viral_trends if v.get('source') != 'google_trends']
all_hype.sort(key=lambda x: x.get('vpd', 0), reverse=True)
google_trends = [v for v in viral_trends if v.get('source') == 'google_trends']

# Сохраняем hype.json
hype_data = {
    "viral_trends": all_hype[:30],
    "google_trends": google_trends,
    "hype_validated": hype_validated,
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
