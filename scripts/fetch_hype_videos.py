#!/usr/bin/env python3
"""
Хайп-видео: маленький канал + много просмотров = вирусный взрыв.
Метрика: views / channel_subs > MIN_RATIO и vpd > MIN_VPD
Алгоритм:
  1. Собираем ~200 кандидатов через scrapetube (разные запросы)
  2. Для каждого делаем yt-dlp запрос → получаем точные данные
  3. Фильтруем по views/subs ratio + vpd
  4. Сохраняем топ в /tmp/hype_videos.json
"""
import subprocess, json, sys, os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import scrapetube
    HAS_SCRAPETUBE = True
except:
    HAS_SCRAPETUBE = False

OUT_FILE = '/tmp/hype_videos.json'
YT_DLP = '/opt/homebrew/bin/yt-dlp'

# Параметры хайп-детекции
MIN_VIEWS     = 50_000     # минимум просмотров
MIN_VPD       = 5_000      # минимум просмотров/день
MIN_RATIO     = 10         # views должны быть в X раз больше подписчиков
MAX_SUBS      = 1_000_000  # канал не должен быть мегапопулярным
MAX_AGE_DAYS  = 45         # видео не старше 45 дней
MAX_WORKERS   = 10         # параллельных yt-dlp запросов

# Запросы для поиска кандидатов
SEARCH_QUERIES = [
    # Игровые тренды
    'viral mobile game 2026',
    'this game blew up 2026',
    'addictive game 2026',
    'game challenge viral 2026',
    'mobile game tiktok trend 2026',
    'satisfying mobile game 2026',
    'новая вирусная игра 2026',
    'игра набирает просмотры 2026',
    # Общий хайп (идеи для игр)
    'viral challenge 2026',
    'tiktok trend 2026',
    'viral video 2026 small channel',
    'this blew up overnight 2026',
    'unexpected viral 2026',
    'went viral 2026',
    'trending now youtube 2026',
    # Разные языки - больше охват
    'viral 2026 jogo',        # BR
    '바이럴 게임 2026',          # KR
    'viral game 2026 india',  # IN
]

def fmt_views(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(v)

def fmt_subs(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(v)

def grade_hype(ratio, vpd):
    if ratio >= 500 and vpd >= 100_000: return "🔥🔥"
    if ratio >= 200 and vpd >= 50_000:  return "🔥"
    if ratio >= 100 and vpd >= 20_000:  return "🚀🔥"
    if ratio >= 50  and vpd >= 10_000:  return "🚀"
    return "⚡"

# ── 1. Сбор кандидатов ─────────────────────────────────────────────────────

candidates = {}  # id → title

if HAS_SCRAPETUBE:
    print(f"Собираю кандидатов ({len(SEARCH_QUERIES)} запросов)...", file=sys.stderr)
    for q in SEARCH_QUERIES:
        try:
            vids = list(scrapetube.get_search(q, limit=20, sleep=0.2))
            for v in vids:
                vid_id = v.get('videoId', '')
                if not vid_id or vid_id in candidates: continue
                # Пре-фильтр по просмотрам (simpleText может быть)
                views_raw = v.get('viewCountText', {})
                views_text = views_raw.get('simpleText', '') if isinstance(views_raw, dict) else ''
                # Пропускаем если явно мало просмотров
                if views_text and ('views' in views_text.lower()):
                    try:
                        num = float(views_text.replace(',','').split()[0].replace('K','000').replace('M','000000'))
                        if num < MIN_VIEWS: continue
                    except: pass
                title = v.get('title', {}).get('runs', [{}])[0].get('text', '')
                candidates[vid_id] = title
        except Exception as e:
            print(f"  skip '{q}': {e}", file=sys.stderr)

    print(f"Кандидатов: {len(candidates)}", file=sys.stderr)
else:
    print("scrapetube не установлен!", file=sys.stderr)
    sys.exit(1)

# ── 2. Проверка каждого видео через yt-dlp ─────────────────────────────────

def check_video(vid_id):
    """Получает точные данные через yt-dlp. Возвращает dict или None."""
    try:
        out = subprocess.check_output(
            [YT_DLP, '--dump-json', '--no-playlist',
             f'https://youtu.be/{vid_id}'],
            timeout=20, stderr=subprocess.DEVNULL
        )
        d = json.loads(out)

        views      = d.get('view_count', 0) or 0
        subs       = d.get('channel_follower_count', 0) or 0
        upload     = d.get('upload_date', '')  # YYYYMMDD
        duration   = d.get('duration', 0) or 0
        title      = d.get('title', '')
        channel    = d.get('channel', '') or d.get('uploader', '')
        channel_id = d.get('channel_id', '')
        thumb      = d.get('thumbnail', '')
        likes      = d.get('like_count', 0) or 0

        # Фильтры
        if views < MIN_VIEWS: return None
        if subs > MAX_SUBS: return None  # слишком большой канал
        if duration > 1800: return None  # не длиннее 30 минут

        # Возраст
        age = 30
        if upload and len(upload) == 8:
            try:
                up = datetime.strptime(upload, '%Y%m%d')
                age = max(1, (datetime.now() - up).days)
            except: pass
        if age > MAX_AGE_DAYS: return None

        vpd = views // age
        if vpd < MIN_VPD: return None

        # Главная метрика хайпа
        ratio = views / max(subs, 1)
        if ratio < MIN_RATIO: return None

        return {
            'id': vid_id,
            'title': title,
            'channel': channel,
            'channel_id': channel_id,
            'views': views,
            'views_str': fmt_views(views),
            'subs': subs,
            'subs_str': fmt_subs(subs),
            'age_days': age,
            'vpd': vpd,
            'vpd_str': fmt_views(vpd),
            'ratio': round(ratio, 1),
            'likes': likes,
            'duration_secs': duration,
            'upload_date': upload,
            'grade': grade_hype(ratio, vpd),
            'url': f'https://youtu.be/{vid_id}',
            'thumb': thumb,
            'source': 'youtube_hype',
            'kind': 'Short' if duration <= 62 else 'Video',
        }
    except Exception:
        return None

print(f"Проверяю {len(candidates)} видео ({MAX_WORKERS} потоков)...", file=sys.stderr)

hype_videos = []
ids_list = list(candidates.keys())
done = 0

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    futures = {ex.submit(check_video, vid_id): vid_id for vid_id in ids_list}
    for fut in as_completed(futures):
        done += 1
        r = fut.result()
        if r:
            hype_videos.append(r)
        if done % 30 == 0:
            print(f"  {done}/{len(ids_list)}, хайп: {len(hype_videos)}...", file=sys.stderr)

# Сортируем по ratio × vpd (комбо-метрика)
hype_videos.sort(key=lambda x: x['ratio'] * x['vpd'], reverse=True)

print(f"\n🔥 Хайп-видео (views/subs > {MIN_RATIO}x, vpd > {MIN_VPD:,}):\n", file=sys.stderr)
for v in hype_videos[:15]:
    k = '🩳' if v['kind'] == 'Short' else '▶'
    print(f"  {k} {v['grade']}  ratio:{v['ratio']:>6.0f}x | {v['vpd_str']:>5}/д | "
          f"subs:{v['subs_str']:>5} | {v['title'][:45]}", file=sys.stderr)

with open(OUT_FILE, 'w') as f:
    json.dump(hype_videos[:30], f, ensure_ascii=False, indent=2)

print(f"\nСохранено: {OUT_FILE} ({len(hype_videos)} хайп-видео из {len(ids_list)} проверенных)", file=sys.stderr)
print(json.dumps({'count': len(hype_videos), 'checked': len(ids_list)}))
