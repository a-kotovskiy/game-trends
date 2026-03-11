#!/usr/bin/env python3
"""Обновляет dashboard/data.json: ракеты Google Play + YouTube видео"""
import subprocess, json, sys, os
from datetime import datetime, timedelta, timezone
import zoneinfo
MSK = zoneinfo.ZoneInfo("Europe/Moscow")

WORKSPACE = "/Users/andrey/.openclaw/workspace"
DATA_FILE = f"{WORKSPACE}/dashboard/data.json"
SCRIPTS = f"{WORKSPACE}/scripts"
SKILL_SCRIPTS = f"{WORKSPACE}/skills/game-hype-radar/scripts"
YT_DLP = "/opt/homebrew/bin/yt-dlp"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

# --- Ракеты Google Play ---
def get_rockets():
    log("Собираю ракеты Google Play...")
    try:
        out = subprocess.check_output(
            ["python3", f"{SCRIPTS}/gplay_rockets.py",
             "--days", "30", "--min-dpd", "1000", "--limit", "10", "--json"],
            timeout=360, stderr=subprocess.DEVNULL
        ).decode().strip()
        if not out:
            log("Ракеты: пустой вывод")
            return []
        rockets = json.loads(out)
        log(f"Ракеты: {len(rockets)} игр")
        return rockets
    except subprocess.TimeoutExpired:
        log("Ракеты: таймаут (180с)")
        return []
    except Exception as e:
        log(f"Ракеты: ошибка - {e}")
        return []

# --- YouTube видео ---
def get_videos():
    log("Собираю YouTube видео...")
    try:
        # Пробуем скрипт из скилла (сохраняет в /tmp/yt_viral_games.json)
        skill_script = f"{SKILL_SCRIPTS}/yt_trends.py"
        if os.path.exists(skill_script):
            subprocess.run(
                ["python3", skill_script],
                timeout=120, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
            )
            tmp = "/tmp/yt_viral_games.json"
            if os.path.exists(tmp):
                with open(tmp) as f:
                    raw = json.load(f)
                # Нормализуем поля (скилл использует 'age', дашборд - 'age_days')
                videos = []
                for v in raw:
                    vid_id = v.get("url", "").split("youtu.be/")[-1].split("?")[0]
                    views = v.get("views", 0)
                    age_days = v.get("age", v.get("age_days", 30))
                    vpd = v.get("vpd", int(views / max(age_days, 1)))
                    if views >= 1_000_000:
                        views_str = f"{views/1_000_000:.1f}M"
                    else:
                        views_str = f"{views//1000}K"
                    pub_text = v.get("published_text", "")
                    # Формируем человекочитаемую дату публикации
                    if pub_text:
                        published = pub_text
                    elif age_days <= 1:
                        published = "сегодня"
                    elif age_days <= 7:
                        published = f"{age_days}д назад"
                    else:
                        published = f"{age_days}д назад"

                    videos.append({
                        "source": "youtube",
                        "kind": "Short" if v.get("is_short") else "Video",
                        "vpd": vpd, "views": views, "views_str": views_str,
                        "age_days": age_days, "title": v.get("title", ""),
                        "channel": v.get("channel", ""),
                        "url": v.get("url", ""),
                        "thumb": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
                        "grade": v.get("grade", "📈"),
                        "published": published,
                    })
                log(f"Видео (скилл): {len(videos)}")
                return videos
    except Exception as e:
        log(f"Видео (скилл): {e}")

    # Фолбэк: прямой yt-dlp
    log("Видео: используем yt-dlp напрямую...")
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
                YT_DLP, "--flat-playlist",
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
            ["python3", f"{SCRIPTS}/fetch_news.py"],
            timeout=60, stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            news = json.loads(out)
            log(f"Новости: {len(news)}")
            return news
    except Exception as e:
        log(f"Новости: ошибка - {e}")
    return []

# --- Идеи (генерируются после ракет и видео) ---
def get_ideas():
    log("Генерирую идеи...")
    try:
        out = subprocess.check_output(
            ["python3", f"{SCRIPTS}/gen_ideas.py"],
            timeout=15, stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            ideas = json.loads(out)
            log(f"Идеи: {len(ideas)}")
            return ideas
    except Exception as e:
        log(f"Идеи: ошибка - {e}")
    return []

# --- TikTok хайп ---
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

# --- Вирусные тренды (YouTube + Google Trends) ---
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

# --- Валидированный хайп ---
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

# --- Главный запуск ---
rockets = get_rockets()
videos = get_videos()
news = get_news()
ideas = get_ideas()
viral_trends = get_viral_trends()
tiktok_hype = get_tiktok_hype()
hype_validated = get_validated_hype()

# Объединяем TikTok + YouTube хайп в один раздел
all_hype = tiktok_hype + [v for v in viral_trends if v.get('source') != 'google_trends']
all_hype.sort(key=lambda x: x.get('vpd', 0), reverse=True)
google_trends = [v for v in viral_trends if v.get('source') == 'google_trends']

# Читаем старые данные чтобы не затирать при частичной ошибке
old_data = {}
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE) as f:
            old_data = json.load(f)
    except: pass

data = {
    "updated": datetime.now(MSK).strftime("%Y-%m-%d %H:%M МСК"),
    "rockets":       rockets       if rockets       else old_data.get("rockets", []),
    "videos":        videos        if videos        else old_data.get("videos", []),
    "news":          news          if news          else old_data.get("news", []),
    "ideas":         ideas         if ideas         else old_data.get("ideas", []),
    "viral_trends":  all_hype[:30] if all_hype      else old_data.get("viral_trends", []),
    "google_trends": google_trends if google_trends else old_data.get("google_trends", []),
    "hype_validated": hype_validated if hype_validated else old_data.get("hype_validated", []),
}

with open(DATA_FILE, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

log(f"✅ data.json обновлён: {len(rockets)} ракет, {len(videos)} видео, {len(news)} новостей, {len(ideas)} идей, {len(viral_trends)} трендов")
print(json.dumps({"rockets": len(rockets), "videos": len(videos), "news": len(news), "ideas": len(ideas)}))
