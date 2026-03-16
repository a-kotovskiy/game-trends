#!/usr/bin/env python3
"""
health_check.py — проверяет консистентность дашборда перед пушем на GitHub.
Выводит OK или список проблем. Exit code 1 если есть критические ошибки.
"""
import json, os, sys
from datetime import datetime, date

DASHBOARD = "/Users/andrey/.openclaw/workspace/dashboard"
SCRIPTS   = "/Users/andrey/.openclaw/workspace/scripts"

errors   = []
warnings = []

def check(name, ok, msg, critical=True):
    mark = "✅" if ok else ("❌" if critical else "⚠️")
    print(f"  {mark} {name}: {msg}")
    if not ok:
        (errors if critical else warnings).append(name)

# --- 1. Файлы существуют ---
print("📁 Файлы:")
for fname in ["rockets.json","hype.json","videos.json","news.json","ideas.json","meta.json","all_rockets_history.json","index.html"]:
    path = f"{DASHBOARD}/{fname}"
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    check(fname, exists and size > 10, f"{'OK' if exists else 'ОТСУТСТВУЕТ'} ({size} байт)")

# --- 2. Ракеты ---
print("\n🚀 Ракеты:")
try:
    with open(f"{DASHBOARD}/rockets.json") as f:
        rockets_raw = json.load(f)
    # Поддержка нового формата {"rockets": [...], "watchlist": [...]} и старого (массив)
    if isinstance(rockets_raw, dict):
        rockets = rockets_raw.get("rockets", [])
        watchlist_rockets = rockets_raw.get("watchlist", [])
    else:
        rockets = rockets_raw
        watchlist_rockets = [r for r in rockets if r.get("isWatchlist")]
    all_rockets = rockets + watchlist_rockets
    check("rockets count", len(rockets) >= 5, f"{len(rockets)} игр (watchlist: {len(watchlist_rockets)})")

    # Обязательные поля
    missing_id = [r.get("name","?") for r in all_rockets if not r.get("id")]
    check("rockets have id", len(missing_id) == 0,
          "OK" if not missing_id else f"нет id у: {missing_id}")

    # One Hit Punch из watchlist
    watchlist_path = f"{SCRIPTS}/watchlist.json"
    if os.path.exists(watchlist_path):
        wl = json.load(open(watchlist_path)).get("apps", [])
        rocket_ids = [r.get("id","") for r in all_rockets]
        missing_wl = [a for a in wl if a not in rocket_ids]
        check("watchlist в ракетах", len(missing_wl) == 0,
              "OK" if not missing_wl else f"нет в rockets.json: {[a.split('.')[-1] for a in missing_wl]}",
              critical=False)

    # Свежесть данных (не старше 2 дней)
    newest_dpd = max((r.get("perDay",0) for r in all_rockets), default=0)
    check("rockets не пустые", newest_dpd > 0, f"top dpd={newest_dpd:,}")
except Exception as e:
    check("rockets.json читается", False, str(e))

# --- 3. История ---
print("\n📊 История:")
try:
    with open(f"{DASHBOARD}/all_rockets_history.json") as f:
        history = json.load(f)
    check("history count", len(history) >= 10, f"{len(history)} игр")

    # Записи за сегодня
    today = str(date.today())
    with_today = sum(1 for v in history.values()
                     if v.get("history") and v["history"][-1]["date"] == today)
    check("history обновлена сегодня", with_today > 0,
          f"{with_today} игр с данными за {today}", critical=False)
except Exception as e:
    check("all_rockets_history.json читается", False, str(e))

# --- 4. Хайп ---
print("\n🔥 Хайп:")
try:
    with open(f"{DASHBOARD}/hype.json") as f:
        hype = json.load(f)
    vt = hype.get("viral_trends", [])
    hv = hype.get("hype_validated", [])
    check("viral_trends", len(vt) >= 5, f"{len(vt)} трендов")
    check("hype_validated", len(hv) >= 1, f"{len(hv)} подтверждённых", critical=False)
except Exception as e:
    check("hype.json читается", False, str(e))

# --- 5. Мета ---
print("\n🕒 Мета:")
try:
    with open(f"{DASHBOARD}/meta.json") as f:
        meta = json.load(f)
    updated = meta.get("updated", "")
    check("meta.updated", bool(updated), updated or "ПУСТО", critical=False)
except Exception as e:
    check("meta.json читается", False, str(e), critical=False)

# --- 6. GitHub синхронизация ---
print("\n📡 GitHub:")
try:
    import subprocess
    r = subprocess.run(["git","status","--short"],
                       capture_output=True, text=True, cwd="/tmp/gh3", timeout=10)
    dirty = [l for l in r.stdout.strip().split("\n") if l.strip()]
    check("github в sync", len(dirty) == 0,
          "OK" if not dirty else f"не запушено: {dirty}", critical=False)
except Exception as e:
    check("github доступен", False, str(e), critical=False)

# --- Итог ---
print()
if errors:
    print(f"❌ КРИТИЧЕСКИЕ ОШИБКИ ({len(errors)}): {', '.join(errors)}")
    sys.exit(1)
elif warnings:
    print(f"⚠️  Предупреждения ({len(warnings)}): {', '.join(warnings)}")
    print("✅ Критических ошибок нет — пуш разрешён")
else:
    print("✅ Всё OK — можно пушить")
