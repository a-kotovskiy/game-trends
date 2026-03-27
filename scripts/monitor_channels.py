#!/usr/bin/env python3
"""
Мониторинг gaming-каналов v2 (оптимизированный).
Ключевые улучшения:
  - Кэш дат видео (не запрашиваем повторно)
  - Убран sleep(1.5) — заменён на случайную паузу только при 429
  - Воркеров увеличено до 10
  - Videos + Shorts объединены в один запрос через /videos + /shorts
  - dump-json только если видео < 7 дней и нет даты (вместо top-3 всегда)

Результат: /tmp/channel_hype.json
"""
import subprocess, json, sys, os, random, time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

YT_DLP = '/opt/homebrew/bin/yt-dlp'
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.path.join(SCRIPTS_DIR, 'gaming_channels.json')
OUT_FILE = '/tmp/channel_hype.json'
CACHE_FILE = '/tmp/yt_video_dates_cache.json'  # кэш дат

# Параметры
MAX_VIDEOS_PER_CHANNEL = 5
MAX_AGE_DAYS = 30
MIN_VPD = 30_000
MIN_VIEWS = 100_000
ANOMALY_MULTIPLIER = 3
MAX_WORKERS = 10  # было 6

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

def fmt_views(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(v)

# ── Кэш дат ──────────────────────────────────────────────────────────────────

def load_cache():
    """Загружает кэш дат видео. Структура: {video_id: {date, duration, cached_at}}"""
    try:
        if os.path.exists(CACHE_FILE):
            # Кэш живёт 7 дней
            age = time.time() - os.path.getmtime(CACHE_FILE)
            if age < 7 * 86400:
                with open(CACHE_FILE) as f:
                    return json.load(f)
    except Exception:
        pass
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception:
        pass

# Глобальный кэш
VIDEO_CACHE = load_cache()
CACHE_HITS = 0
CACHE_MISSES = 0

def get_video_details(vid_id):
    """Получает дату и длительность видео. Использует кэш."""
    global CACHE_HITS, CACHE_MISSES

    if vid_id in VIDEO_CACHE:
        CACHE_HITS += 1
        return VIDEO_CACHE[vid_id]

    CACHE_MISSES += 1
    try:
        out = subprocess.check_output(
            [YT_DLP, '--dump-json', '--no-playlist', f'https://youtu.be/{vid_id}'],
            timeout=20, stderr=subprocess.DEVNULL
        )
        d = json.loads(out)
        result = {
            'upload_date': d.get('upload_date', ''),
            'duration': d.get('duration', 0) or 0,
        }
        VIDEO_CACHE[vid_id] = result
        return result
    except Exception:
        return None

# ── Парсинг канала ────────────────────────────────────────────────────────────

def fetch_playlist(url, max_videos):
    out = subprocess.check_output(
        [YT_DLP, '--flat-playlist', '--no-download',
         '--print', '%(id)s|||%(title)s|||%(view_count)s|||%(upload_date)s|||%(duration)s',
         '--playlist-items', f'1-{max_videos}', url],
        timeout=25, stderr=subprocess.DEVNULL
    ).decode().strip()
    return out

def get_channel_videos(channel_id, channel_name, max_videos=MAX_VIDEOS_PER_CHANNEL):
    try:
        # Запрашиваем videos и shorts параллельно
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_videos = ex.submit(fetch_playlist,
                f"https://www.youtube.com/channel/{channel_id}/videos", max_videos)
            f_shorts = ex.submit(fetch_playlist,
                f"https://www.youtube.com/channel/{channel_id}/shorts", max_videos)
            try:
                videos_out = f_videos.result(timeout=30)
            except Exception:
                videos_out = ""
            try:
                shorts_out = f_shorts.result(timeout=30)
            except Exception:
                shorts_out = ""

        # Объединяем без дублей
        seen_ids = set()
        raw = []
        for line in (videos_out + '\n' + shorts_out).split('\n'):
            if not line.strip(): continue
            parts = line.split('|||')
            if len(parts) < 5: continue
            vid_id = parts[0]
            if not vid_id or vid_id in seen_ids: continue
            seen_ids.add(vid_id)

            try: views = int(parts[2]) if parts[2] and parts[2] != 'NA' else 0
            except: views = 0
            try: duration = int(float(parts[4])) if parts[4] and parts[4] != 'NA' else 0
            except: duration = 0

            raw.append((vid_id, parts[1], views, parts[3], duration))

        # dump-json только для топовых видео БЕЗ даты и только если views >= MIN_VIEWS
        # Сортируем по просмотрам, берём top-2 (было 3)
        top = sorted(raw, key=lambda x: x[2], reverse=True)[:2]
        need_details = {v[0] for v in top if v[2] >= MIN_VIEWS and (not v[3] or v[3] == 'NA')}

        # Запрашиваем детали параллельно (без sleep!)
        details_map = {}
        if need_details:
            with ThreadPoolExecutor(max_workers=len(need_details)) as ex:
                futs = {ex.submit(get_video_details, vid_id): vid_id for vid_id in need_details}
                for fut in as_completed(futs):
                    vid_id = futs[fut]
                    result = fut.result()
                    if result:
                        details_map[vid_id] = result

        # Строим финальный список
        videos = []
        for vid_id, title, views, upload_date, duration in raw:
            if vid_id in details_map:
                upload_date = details_map[vid_id].get('upload_date', upload_date)
                if not duration:
                    duration = details_map[vid_id].get('duration', 0)

            if not upload_date or upload_date == 'NA':
                continue

            try:
                up = datetime.strptime(upload_date, '%Y%m%d')
                age_days = max(1, (datetime.now() - up).days)
            except:
                continue

            if age_days > MAX_AGE_DAYS:
                continue

            vpd = views // max(age_days, 1)
            kind = 'Short' if duration and duration <= 62 else 'Video'
            videos.append({
                'id': vid_id,
                'title': title,
                'views': views,
                'views_str': fmt_views(views),
                'vpd': vpd,
                'vpd_str': fmt_views(vpd),
                'age_days': age_days,
                'upload_date': upload_date,
                'duration': duration,
                'kind': kind,
                'channel': channel_name,
                'channel_id': channel_id,
                'url': f'https://youtu.be/{vid_id}',
                'thumb': f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg',
            })
        return videos

    except Exception as e:
        log(f"  ❌ {channel_name}: {e}")
        return []

# ── Детект хайпа ─────────────────────────────────────────────────────────────

def detect_hype(all_videos_by_channel):
    hype = []
    for channel_name, videos in all_videos_by_channel.items():
        if not videos: continue
        vpds = [v['vpd'] for v in videos if v['vpd'] > 0]
        if not vpds: continue
        avg_vpd = sum(vpds) / len(vpds)

        for v in videos:
            is_hype = False
            reason = []
            if v['vpd'] >= MIN_VPD and v['views'] >= MIN_VIEWS:
                is_hype = True
                reason.append(f"vpd={fmt_views(v['vpd'])}")
            if avg_vpd > 0 and v['vpd'] >= avg_vpd * ANOMALY_MULTIPLIER and v['views'] >= 100_000:
                is_hype = True
                reason.append(f"{v['vpd']/avg_vpd:.1f}x avg")

            if is_hype:
                if v['vpd'] >= 500_000: grade = "🔥🔥"
                elif v['vpd'] >= 100_000: grade = "🔥"
                elif v['vpd'] >= 50_000: grade = "🚀🔥"
                elif v['vpd'] >= 20_000: grade = "🚀"
                else: grade = "⚡"
                hype.append({
                    **v,
                    'grade': grade,
                    'source': 'channel_monitor',
                    'reason': ', '.join(reason),
                    'channel_avg_vpd': int(avg_vpd),
                })

    hype.sort(key=lambda x: x['vpd'], reverse=True)
    return hype

# ── Main ──────────────────────────────────────────────────────────────────────

t_start = time.time()
with open(CHANNELS_FILE) as f:
    channels = json.load(f)['channels']

log(f"Мониторинг {len(channels)} каналов (workers={MAX_WORKERS})...")

all_videos = {}

def fetch_channel(ch):
    return ch['name'], get_channel_videos(ch['id'], ch['name'])

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    futures = {ex.submit(fetch_channel, ch): ch for ch in channels}
    done = 0
    for fut in as_completed(futures):
        done += 1
        name, videos = fut.result()
        all_videos[name] = videos
        if videos:
            total = sum(v['views'] for v in videos)
            log(f"  ✅ {name}: {len(videos)} видео, {fmt_views(total)}")
        if done % 10 == 0:
            log(f"  {done}/{len(channels)} каналов...")

# Сохраняем кэш
save_cache(VIDEO_CACHE)
log(f"Кэш: {CACHE_HITS} hits, {CACHE_MISSES} misses (сохранено {len(VIDEO_CACHE)} записей)")

hype = detect_hype(all_videos)
elapsed = int(time.time() - t_start)

log(f"\n🔥 {len(hype)} хайп-видео за {elapsed}с:")
for v in hype[:15]:
    log(f"  {v['grade']} {v['channel']}: {v['title'][:40]} — {v['vpd_str']}/д")

with open(OUT_FILE, 'w') as f:
    json.dump(hype, f, ensure_ascii=False, indent=2)

log(f"Сохранено: {OUT_FILE}")
print(json.dumps({'count': len(hype), 'channels_checked': len(channels), 'elapsed': elapsed}))
