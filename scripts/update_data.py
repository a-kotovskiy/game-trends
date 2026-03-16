#!/usr/bin/env python3
"""Обновляет data.json + отдельные JSON файлы секций (GitHub Actions version)"""
import subprocess, json, sys, os
from datetime import datetime, timedelta, timezone
import zoneinfo
MSK = zoneinfo.ZoneInfo("Europe/Moscow")

# Paths relative to this script (scripts/ dir inside repo)
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.dirname(SCRIPTS)  # repo root = dashboard files root
DATA_FILE = os.path.join(DASHBOARD, "data.json")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

def save_section(name, data):
    """Сохраняет секцию. Если data пустой — сохраняет старые данные."""
    path = os.path.join(DASHBOARD, f"{name}.json")
    if not data:
        if os.path.exists(path):
            log(f"  {name}: пустой результат, сохраняем старые данные")
            return
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if isinstance(data, list):
        log(f"  {name}: {len(data)} записей")
    else:
        log(f"  {name}: сохранено")

# --- Ракеты Google Play ---
def get_rockets():
    log("Собираю ракеты Google Play...")
    try:
        out = subprocess.check_output(
            ["python3", os.path.join(SCRIPTS, "gplay_rockets.py"),
             "--days", "30", "--min-dpd", "1000", "--limit", "10", "--json"],
            timeout=1200, stderr=subprocess.DEVNULL
        ).decode().strip()
        if not out:
            log("Ракеты: пустой вывод")
            return []
        rockets = json.loads(out)
        log(f"Ракеты: {len(rockets)} игр")
        return rockets
    except subprocess.TimeoutExpired:
        log("Ракеты: таймаут")
        return []
    except Exception as e:
        log(f"Ракеты: ошибка - {e}")
        return []

# --- YouTube видео (yt-dlp fallback only — no TikTok in CI) ---
def get_videos():
    log("Собираю YouTube видео...")
    queries = [
        "viral mobile game 2026",
        "everyone playing this game 2026",
        "new game blowing up 2026",
    ]
    all_videos = []
    seen = set()
    cutoff = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

    for q in queries:
        try:
            out = subprocess.check_output([
                "yt-dlp", "--flat-playlist",
                "--print", "%(view_count)s ||| %(title)s ||| %(url)s ||| %(channel)s ||| %(upload_date)s",
                "--dateafter", cutoff,
                f"ytsearch15:{q}"
            ], timeout=45, stderr=subprocess.DEVNULL).decode()
            for line in out.strip().split("\n"):
                parts = line.split(" ||| ")
                if len(parts) < 4: continue
                try:
                    views = int(parts[0])
                    url = parts[2].strip()
                    if views < 100_000 or url in seen: continue
                    seen.add(url)
                    channel = parts[3].strip() if len(parts) > 3 else ""
                    upload_date = parts[4].strip() if len(parts) > 4 else ""
                    age_days = 30
                    if upload_date and len(upload_date) == 8:
                        try:
                            d = datetime.strptime(upload_date, "%Y%m%d")
                            age_days = max(1, (datetime.now() - d).days)
                        except: pass
                    vpd = int(views / age_days)
                    if vpd < 1000: continue
                    vid_id = url.split("watch?v=")[-1].split("&")[0] if "watch?v=" in url else ""
                    if views >= 1_000_000:
                        views_str = f"{views/1_000_000:.1f}M"
                    else:
                        views_str = f"{views//1000}K"
                    if vpd >= 500_000: grade = "🚀🔥"
                    elif vpd >= 100_000: grade = "🚀"
                    elif vpd >= 30_000: grade = "⚡"
                    else: grade = "📈"
                    all_videos.append({
                        "vpd": vpd, "views": views, "views_str": views_str,
                        "age_days": age_days, "title": parts[1].strip(),
                        "channel": channel, "url": url,
                        "thumb": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
                        "grade": grade
                    })
                except: pass
        except Exception as e:
            log(f"  yt-dlp '{q}': {e}")

    all_videos.sort(key=lambda x: x["vpd"], reverse=True)
    result = all_videos[:15]
    log(f"Видео: {len(result)}")
    return result

# --- Новости ---
def get_news():
    log("Собираю новости...")
    try:
        out = subprocess.check_output(
            ["python3", os.path.join(SCRIPTS, "fetch_news.py")],
            timeout=60, stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            news = json.loads(out)
            log(f"Новости: {len(news)}")
            return news
    except Exception as e:
        log(f"Новости: ошибка - {e}")
    return []

# --- Идеи ---
def get_ideas():
    log("Генерирую идеи...")
    try:
        out = subprocess.check_output(
            ["python3", os.path.join(SCRIPTS, "gen_ideas.py")],
            timeout=15, stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            ideas = json.loads(out)
            log(f"Идеи: {len(ideas)}")
            return ideas
    except Exception as e:
        log(f"Идеи: ошибка - {e}")
    return []

# --- Вирусные тренды (YouTube) ---
def get_viral_trends():
    log("Собираю вирусные тренды...")
    try:
        result = subprocess.run(
            ["python3", os.path.join(SCRIPTS, "fetch_viral_videos.py")],
            timeout=180, stderr=subprocess.DEVNULL, stdout=subprocess.PIPE
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

# --- Главный запуск ---
rockets = get_rockets()
videos = get_videos()
news = get_news()
ideas = get_ideas()
viral_trends = get_viral_trends()

all_hype = [v for v in viral_trends if v.get('source') != 'google_trends']
all_hype.sort(key=lambda x: x.get('vpd', 0), reverse=True)
google_trends = [v for v in viral_trends if v.get('source') == 'google_trends']

# Читаем старые данные чтобы не затирать при частичной ошибке
old_data = {}
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE) as f:
            old_data = json.load(f)
    except: pass

updated = datetime.now(MSK).strftime("%Y-%m-%d %H:%M МСК")

data = {
    "updated": updated,
    "rockets":       rockets       if rockets       else old_data.get("rockets", []),
    "videos":        videos        if videos        else old_data.get("videos", []),
    "news":          news          if news          else old_data.get("news", []),
    "ideas":         ideas         if ideas         else old_data.get("ideas", []),
    "viral_trends":  all_hype[:30] if all_hype      else old_data.get("viral_trends", []),
    "google_trends": google_trends if google_trends else old_data.get("google_trends", []),
    "hype_validated": old_data.get("hype_validated", []),
}

# Сохраняем data.json (обратная совместимость)
with open(DATA_FILE, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# Сохраняем отдельные секции
log("Сохраняю отдельные секции...")
save_section("rockets", data["rockets"])
save_section("videos", data["videos"])
save_section("news", data["news"])
save_section("ideas", data["ideas"])
save_section("hype", {
    "viral_trends": data["viral_trends"],
    "google_trends": data["google_trends"],
    "hype_validated": data["hype_validated"],
})

# meta.json
meta = {
    "updated": updated,
    "rockets_count": len(data["rockets"]),
    "videos_count": len(data["videos"]),
    "news_count": len(data["news"]),
    "ideas_count": len(data["ideas"]),
    "hype_count": len(data["viral_trends"]),
    "google_trends_count": len(data["google_trends"]),
    "hype_validated_count": len(data["hype_validated"]),
}
with open(os.path.join(DASHBOARD, "meta.json"), "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
log("  meta.json: сохранено")

log(f"✅ Обновлено: {len(data['rockets'])} ракет, {len(data['videos'])} видео, {len(data['news'])} новостей, {len(data['ideas'])} идей, {len(data['viral_trends'])} трендов")
print(json.dumps({"rockets": len(data["rockets"]), "videos": len(data["videos"]), "news": len(data["news"]), "ideas": len(data["ideas"])}))
