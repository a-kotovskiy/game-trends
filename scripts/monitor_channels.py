#!/usr/bin/env python3
"""
Мониторинг gaming-каналов: ищет хайп-видео у отслеживаемых ютуберов.
Проверяет последние видео каждого канала, находит те что набирают аномально много просмотров.

Результат: /tmp/channel_hype.json — массив хайп-видео для включения в hype.json
"""
import subprocess, json, sys, os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

YT_DLP = '/opt/homebrew/bin/yt-dlp'
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.path.join(SCRIPTS_DIR, 'gaming_channels.json')
OUT_FILE = '/tmp/channel_hype.json'

# Параметры
MAX_VIDEOS_PER_CHANNEL = 10   # последних видео проверяем
MAX_AGE_DAYS = 30              # не старше 30 дней
MIN_VPD = 50_000               # минимум просмотров/день для хайпа
MIN_VIEWS = 200_000            # минимум просмотров
ANOMALY_MULTIPLIER = 3         # видео набрало в X раз больше среднего для канала
MAX_WORKERS = 8

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

def fmt_views(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(v)

def get_video_details(vid_id):
    """Получает точные данные видео (дата, подписчики) через yt-dlp --dump-json."""
    try:
        out = subprocess.check_output(
            [YT_DLP, '--dump-json', '--no-playlist', f'https://youtu.be/{vid_id}'],
            timeout=20, stderr=subprocess.DEVNULL
        )
        d = json.loads(out)
        return {
            'upload_date': d.get('upload_date', ''),
            'channel_follower_count': d.get('channel_follower_count', 0) or 0,
            'view_count': d.get('view_count', 0) or 0,
            'duration': d.get('duration', 0) or 0,
        }
    except Exception:
        return None

def get_channel_videos(channel_id, channel_name, max_videos=MAX_VIDEOS_PER_CHANNEL):
    """Получает последние видео канала через yt-dlp."""
    try:
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
        out = subprocess.check_output(
            [YT_DLP, '--flat-playlist', '--no-download',
             '--print', '%(id)s|||%(title)s|||%(view_count)s|||%(upload_date)s|||%(duration)s',
             '--playlist-items', f'1-{max_videos}',
             url],
            timeout=30, stderr=subprocess.DEVNULL
        ).decode().strip()

        videos = []
        for line in out.split('\n'):
            if not line.strip(): continue
            parts = line.split('|||')
            if len(parts) < 5: continue
            vid_id, title, views_str, upload_date, duration_str = parts[:5]
            try:
                views = int(views_str) if views_str and views_str != 'NA' else 0
            except: views = 0
            try:
                duration = int(float(duration_str)) if duration_str and duration_str != 'NA' else 0
            except: duration = 0

            # flat-playlist часто не отдаёт дату — делаем точный запрос для популярных видео
            if (not upload_date or upload_date == 'NA') and views >= 50_000:
                details = get_video_details(vid_id)
                if details:
                    upload_date = details.get('upload_date', '')
                    if not duration:
                        duration = details.get('duration', 0)

            age_days = 30
            if upload_date and len(upload_date) == 8:
                try:
                    up = datetime.strptime(upload_date, '%Y%m%d')
                    age_days = max(1, (datetime.now() - up).days)
                except: pass
            elif not upload_date or upload_date == 'NA':
                # Нет даты — пропускаем, чтобы не засорять старыми видео
                continue

            if age_days > MAX_AGE_DAYS: continue

            vpd = views // max(age_days, 1)
            videos.append({
                'id': vid_id,
                'title': title,
                'views': views,
                'vpd': vpd,
                'age_days': age_days,
                'upload_date': upload_date,
                'duration': duration,
                'channel': channel_name,
                'channel_id': channel_id,
            })
        return videos
    except Exception as e:
        log(f"  ❌ {channel_name}: {e}")
        return []

def detect_hype(all_videos_by_channel):
    """Находит аномально популярные видео."""
    hype = []

    for channel_name, videos in all_videos_by_channel.items():
        if not videos: continue

        # Средний vpd для канала
        vpds = [v['vpd'] for v in videos if v['vpd'] > 0]
        if not vpds: continue
        avg_vpd = sum(vpds) / len(vpds)

        for v in videos:
            is_hype = False
            reason = []

            # Критерий 1: абсолютный хайп (много vpd)
            if v['vpd'] >= MIN_VPD and v['views'] >= MIN_VIEWS:
                is_hype = True
                reason.append(f"vpd={fmt_views(v['vpd'])}")

            # Критерий 2: аномалия для канала (в X раз больше среднего)
            if avg_vpd > 0 and v['vpd'] >= avg_vpd * ANOMALY_MULTIPLIER and v['views'] >= 100_000:
                is_hype = True
                reason.append(f"{v['vpd']/avg_vpd:.1f}x avg")

            if is_hype:
                vid_id = v['id']
                kind = 'Short' if v['duration'] and v['duration'] <= 62 else 'Video'
                thumb = f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"

                if v['vpd'] >= 500_000: grade = "🔥🔥"
                elif v['vpd'] >= 100_000: grade = "🔥"
                elif v['vpd'] >= 50_000: grade = "🚀🔥"
                elif v['vpd'] >= 20_000: grade = "🚀"
                else: grade = "⚡"

                hype.append({
                    'id': vid_id,
                    'title': v['title'],
                    'channel': v['channel'],
                    'channel_id': v['channel_id'],
                    'views': v['views'],
                    'views_str': fmt_views(v['views']),
                    'vpd': v['vpd'],
                    'vpd_str': fmt_views(v['vpd']),
                    'age_days': v['age_days'],
                    'upload_date': v['upload_date'],
                    'grade': grade,
                    'url': f'https://youtu.be/{vid_id}',
                    'thumb': thumb,
                    'source': 'channel_monitor',
                    'kind': kind,
                    'reason': ', '.join(reason),
                    'channel_avg_vpd': int(avg_vpd),
                })

    hype.sort(key=lambda x: x['vpd'], reverse=True)
    return hype

# ── Main ──

# Загружаем список каналов
with open(CHANNELS_FILE) as f:
    channels = json.load(f)['channels']

log(f"Мониторинг {len(channels)} каналов...")

# Собираем видео параллельно
all_videos = {}

def fetch_channel(ch):
    videos = get_channel_videos(ch['id'], ch['name'])
    return ch['name'], videos

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    futures = {ex.submit(fetch_channel, ch): ch for ch in channels}
    done = 0
    for fut in as_completed(futures):
        done += 1
        name, videos = fut.result()
        all_videos[name] = videos
        total_views = sum(v['views'] for v in videos)
        if videos:
            log(f"  ✅ {name}: {len(videos)} видео, {fmt_views(total_views)} просмотров")
        if done % 10 == 0:
            log(f"  {done}/{len(channels)} каналов...")

# Детектим хайп
hype = detect_hype(all_videos)

log(f"\n🔥 Найдено {len(hype)} хайп-видео:")
for v in hype[:20]:
    log(f"  {v['grade']} {v['channel']}: {v['title'][:40]}... — {v['vpd_str']}/д ({v['reason']})")

# Сохраняем
with open(OUT_FILE, 'w') as f:
    json.dump(hype, f, ensure_ascii=False, indent=2)

log(f"\nСохранено: {OUT_FILE} ({len(hype)} видео)")
print(json.dumps({'count': len(hype), 'channels_checked': len(channels)}))
