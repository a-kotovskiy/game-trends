#!/usr/bin/env python3
"""Обновляет только rockets.json + meta.json"""
import subprocess, json, sys, os
from datetime import datetime
import zoneinfo
MSK = zoneinfo.ZoneInfo("Europe/Moscow")

WORKSPACE = "/Users/andrey/.openclaw/workspace"
DASHBOARD = f"{WORKSPACE}/dashboard"
SCRIPTS = f"{WORKSPACE}/scripts"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

def get_rockets():
    log("Собираю ракеты Google Play...")
    try:
        result = subprocess.run(
            ["python3", f"{SCRIPTS}/gplay_rockets.py",
             "--days", "30", "--min-dpd", "500", "--limit", "50", "--json"],
            timeout=480, capture_output=True
        )
        out = result.stdout.decode().strip()
        if result.returncode != 0:
            err = result.stderr.decode().strip().split('\n')[-1]
            log(f"Ракеты: парсер вернул код {result.returncode} ({err}), пробую парсить stdout")
        if not out:
            log("Ракеты: пустой вывод")
            return None
        data = json.loads(out)
        # Поддержка нового формата {"rockets": [...], "watchlist": [...]}
        if isinstance(data, dict):
            rockets = data.get("rockets", [])
            watchlist = data.get("watchlist", [])
            log(f"Ракеты: {len(rockets)} топ + {len(watchlist)} watchlist")
            return data
        else:
            # Старый формат - список
            log(f"Ракеты: {len(data)} игр (старый формат)")
            return {"rockets": data, "watchlist": []}
    except subprocess.TimeoutExpired:
        log("Ракеты: таймаут")
        return None
    except json.JSONDecodeError as e:
        log(f"Ракеты: ошибка парсинга JSON - {e}")
        return None
    except Exception as e:
        log(f"Ракеты: ошибка - {e}")
        return None

data = get_rockets()

# Сохраняем rockets.json
path = f"{DASHBOARD}/rockets.json"
if data:
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    total = len(data.get("rockets", [])) + len(data.get("watchlist", []))
    log(f"rockets.json: {total} записей")
elif os.path.exists(path):
    log("rockets.json: пустой результат, сохраняем старые данные")
    # Читаем старые данные для meta
    try:
        with open(path) as f:
            data = json.load(f)
    except:
        data = None

# Обновляем meta.json
meta_path = f"{DASHBOARD}/meta.json"
meta = {}
if os.path.exists(meta_path):
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except: pass

if data:
    rockets = data.get("rockets", []) if isinstance(data, dict) else data
    watchlist = data.get("watchlist", []) if isinstance(data, dict) else []
    meta["rockets_count"] = len(rockets)
    meta["watchlist_count"] = len(watchlist)
    meta["rockets_updated"] = datetime.now(MSK).strftime("%Y-%m-%d %H:%M МСК")
    meta["updated"] = meta["rockets_updated"]
    with open(meta_path, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

log("✅ Ракеты обновлены")
