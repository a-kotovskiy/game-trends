#!/usr/bin/env python3
"""
Перекрёстная проверка хайпа: TikTok + YouTube + Google Trends.
Читает /tmp/tiktok_foryou.json, валидирует через scrapetube и Google Trends RSS.
Результат: /tmp/hype_validated.json
"""
import asyncio, json, re, sys, time, xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_sound_popularity import get_sound_usage

INPUT = '/tmp/tiktok_foryou.json'
OUTPUT = '/tmp/hype_validated.json'
MIN_VIEWS = 1_000_000
MAX_ITEMS = 20
MAX_YT_AGE = 45  # дней — максимальный возраст YT видео для подтверждения
MAX_GT_AGE = 7   # дней — максимальный возраст Google Trends записи
TRENDS_RSS = 'https://trends.google.com/trending/rss?geo=US'

# Мусорные хэштеги TikTok
JUNK_TAGS = {
    'fyp', 'foryou', 'foryoupage', 'viral', 'trending', 'xyzbca', 'xyz',
    'fypシ', 'tiktok', 'trend', 'parati', 'pourtoi', 'liveincentiveprogram',
    'livefest2026', 'makelivecount', 'paidpartnership', 'live', 'duet',
    'stitch', 'greenscreen', 'capcut', 'edit', 'funny', 'comedy', 'meme',
}

def log(msg):
    print(f"[validate] {msg}", file=sys.stderr)

def estimate_yt_age(pub_text):
    """Парсит publishedTimeText из scrapetube в количество дней."""
    if not pub_text:
        return 999
    t = pub_text.lower().strip()
    m = re.match(r'(\d+)\s+(hour|day|week|month|year)', t)
    if not m:
        # "Streamed X days ago" и подобные варианты
        m = re.search(r'(\d+)\s+(hour|day|week|month|year)', t)
    if not m:
        return 999
    n = int(m.group(1))
    unit = m.group(2)
    if unit == 'hour':
        return 0
    elif unit == 'day':
        return n
    elif unit == 'week':
        return n * 7
    elif unit == 'month':
        return n * 30
    elif unit == 'year':
        return n * 365
    return 999

def extract_keywords(desc):
    """Извлекает 2-5 значимых ключевых слов из описания TikTok."""
    if not desc:
        return []
    # Убираем URL
    text = re.sub(r'https?://\S+', '', desc)
    # Извлекаем хэштеги (без мусорных)
    hashtags = re.findall(r'#(\w+)', text.lower())
    good_tags = [t for t in hashtags if t not in JUNK_TAGS and len(t) > 2]
    # Убираем хэштеги из текста, берём слова
    clean = re.sub(r'#\w+', '', text).strip()
    # Берём значимые слова (>3 букв, не стоп-слова)
    stop = {'this', 'that', 'with', 'from', 'have', 'been', 'what', 'when',
            'your', 'they', 'will', 'just', 'like', 'than', 'them', 'only',
            'come', 'made', 'over', 'such', 'some', 'very', 'much', 'also',
            'into', 'back', 'know', 'would', 'could', 'should', 'about',
            'people', 'think', 'every', 'still', 'going', 'really', 'these'}
    words = [w for w in re.findall(r'[a-zA-Z]{4,}', clean.lower()) if w not in stop]
    # Комбинируем: сначала хэштеги, потом слова
    keywords = good_tags[:3] + words[:3]
    # Дедупликация с сохранением порядка
    seen = set()
    result = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result[:5]

def parse_pub_date(pub_date_str):
    """Парсит pubDate из RSS в дни назад. Возвращает int или 999."""
    from email.utils import parsedate_to_datetime
    if not pub_date_str:
        return 999
    try:
        from datetime import datetime, timezone
        dt = parsedate_to_datetime(pub_date_str.strip())
        now = datetime.now(timezone.utc)
        delta = now - dt
        return max(0, delta.days)
    except Exception:
        return 999

def fetch_google_trends():
    """Получает текущие Google Trends из RSS. Фильтрует по свежести (MAX_GT_AGE дней)."""
    log("Загружаю Google Trends RSS...")
    try:
        req = Request(TRENDS_RSS, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode('utf-8')
        root = ET.fromstring(xml_data)
        ns = {'ht': 'https://trends.google.com/trending/rss'}
        trends = set()
        skipped = 0
        for item in root.findall('.//item'):
            # Проверяем свежесть по pubDate
            pub_date = item.findtext('pubDate', '')
            age_days = parse_pub_date(pub_date)
            if age_days > MAX_GT_AGE:
                skipped += 1
                continue
            title = item.findtext('title', '')
            if title:
                trends.add(title.lower().strip())
            # Также берём related topics
            for news in item.findall('.//ht:news_item', ns):
                snippet = news.findtext('ht:news_item_title', '', ns)
                if snippet:
                    for word in re.findall(r'[a-zA-Z]{4,}', snippet.lower()):
                        trends.add(word)
        log(f"Google Trends: {len(trends)} тем (пропущено {skipped} старых)")
        return trends
    except Exception as e:
        log(f"Google Trends ошибка: {e}")
        return set()

def check_google_trends(keywords, trends_set):
    """Проверяет совпадение ключевых слов с Google Trends. Возвращает совпавшее слово или None."""
    for kw in keywords:
        kw_lower = kw.lower()
        for trend in trends_set:
            if kw_lower in trend or trend in kw_lower:
                return kw_lower
    return None

def extract_yt_video_id(url):
    """Извлекает video ID из YouTube URL."""
    m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url or '')
    return m.group(1) if m else None

def parse_views(text):
    """Парсит '1.2M views' или '500K views' в число."""
    if not text:
        return 0
    text = str(text).lower().replace(',', '').replace(' views', '').replace(' view', '').strip()
    try:
        if 'm' in text:
            return int(float(text.replace('m', '')) * 1_000_000)
        if 'k' in text:
            return int(float(text.replace('k', '')) * 1_000)
        return int(text)
    except (ValueError, TypeError):
        return 0

def search_youtube(keywords):
    """Ищет похожие видео на YouTube через scrapetube."""
    import scrapetube
    query = ' '.join(keywords)
    if not query.strip():
        return []
    try:
        results = []
        for video in scrapetube.get_search(query, limit=5):
            title = video.get('title', {})
            if isinstance(title, dict):
                title = title.get('runs', [{}])[0].get('text', '')
            view_text = video.get('viewCountText', {})
            if isinstance(view_text, dict):
                view_text = view_text.get('simpleText', view_text.get('runs', [{}])[0].get('text', ''))
            views = parse_views(view_text)
            if views >= 100_000:
                vid_id = video.get('videoId', '')
                pub_raw = video.get('publishedTimeText', {})
                pub_text = pub_raw.get('simpleText', '') if isinstance(pub_raw, dict) else str(pub_raw)
                age_days = estimate_yt_age(pub_text)
                # Фильтр: только видео не старше MAX_YT_AGE дней
                if age_days > MAX_YT_AGE:
                    continue
                results.append({
                    'title': str(title)[:100],
                    'views_str': view_text if isinstance(view_text, str) else str(views),
                    'views': views,
                    'published': pub_text,
                    'age_days': age_days,
                    'url': f'https://youtube.com/watch?v={vid_id}',
                    'thumb': f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg' if vid_id else '',
                })
            if len(results) >= 3:
                break
        return results
    except Exception as e:
        log(f"  YouTube поиск '{query}': {e}")
        return []

def main():
    # 1. Читаем TikTok данные
    try:
        with open(INPUT) as f:
            tiktok_data = json.load(f)
        log(f"Загружено {len(tiktok_data)} TikTok видео")
    except FileNotFoundError:
        log(f"Файл {INPUT} не найден!")
        sys.exit(1)

    # Фильтруем 1M+ просмотров, сортируем по vpd, берём топ MAX_ITEMS
    filtered = [v for v in tiktok_data if v.get('views', 0) >= MIN_VIEWS]
    filtered.sort(key=lambda x: x.get('vpd', 0), reverse=True)
    filtered = filtered[:MAX_ITEMS]
    log(f"После фильтра 1M+: {len(filtered)} видео")

    # 2. Загружаем Google Trends
    trends_set = fetch_google_trends()

    # 3. Проверяем каждое видео
    results = []
    for i, video in enumerate(filtered):
        title = video.get('title', '')
        keywords = extract_keywords(title)
        log(f"  [{i+1}/{len(filtered)}] '{title[:50]}' -> keywords: {keywords}")

        platforms = ['tiktok']
        yt_videos = []
        hype_score = 1

        # YouTube проверка
        if keywords:
            yt_videos = search_youtube(keywords)
            if yt_videos:
                platforms.append('youtube')
                hype_score = 2
                log(f"    YouTube: {len(yt_videos)} совпадений")
            time.sleep(0.5)

        # Google Trends проверка
        gt_keyword = None
        if keywords:
            gt_keyword = check_google_trends(keywords, trends_set)
        if gt_keyword:
            platforms.append('google_trends')
            hype_score = 3
            log(f"    Google Trends: совпадение '{gt_keyword}'!")

        # Проверка популярности звука (только для чужих треков)
        music_id = video.get('music_id', '')
        music_original = video.get('music_original', False)
        if music_id and not music_original:
            try:
                sound_data = asyncio.run(get_sound_usage(music_id))
                video_count = sound_data.get('video_count', 0)
                if video_count >= 10_000:
                    video['sound_viral'] = True
                    video['sound_video_count'] = video_count
                    video['sound_title'] = sound_data.get('title', '')
                    video['sound_author'] = sound_data.get('author', '')
                    hype_score = min(hype_score + 1, 4)
                    log(f"    Sound viral: {video_count:,} videos — {sound_data.get('title','')}")
                time.sleep(0.3)
            except Exception as e:
                log(f"    Sound check error: {e}")

        # Добавляем thumb к yt_videos если отсутствует
        for yt in yt_videos:
            if 'thumb' not in yt:
                vid_id = extract_yt_video_id(yt.get('url', ''))
                if vid_id:
                    yt['thumb'] = f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg'

        # Определяем свежесть YT и совместный хайп
        tiktok_age = video.get('age_days', 999)
        best_yt_age = min((y.get('age_days', 999) for y in yt_videos), default=999)

        if best_yt_age <= 14:
            yt_freshness = 'fresh'
        elif best_yt_age <= 45:
            yt_freshness = 'recent'
        else:
            yt_freshness = 'old'

        # joint_hype: оба видео (TikTok + хотя бы 1 YT) появились в рамках 30 дней
        joint_hype = False
        if yt_videos:
            for yt in yt_videos:
                yt_age = yt.get('age_days', 999)
                if tiktok_age <= 30 and yt_age <= 30:
                    joint_hype = True
                    break

        # Добавляем поля валидации
        video['hype_score'] = hype_score
        video['hype_confirmed'] = hype_score >= 2
        video['platforms'] = platforms
        video['yt_videos'] = yt_videos[:3]
        video['keywords'] = keywords
        video['yt_freshness'] = yt_freshness
        video['joint_hype'] = joint_hype
        if gt_keyword:
            video['gt_keyword'] = gt_keyword
            video['gt_url'] = f'https://trends.google.com/trends/explore?q={gt_keyword}&geo=US'

        results.append(video)
        if keywords:
            time.sleep(0.5)

    # 4. Фильтруем confirmed, сортируем по hype_score * vpd
    confirmed = [r for r in results if r['hype_confirmed']]
    confirmed.sort(key=lambda x: x['hype_score'] * x.get('vpd', 0), reverse=True)

    log(f"\nИтого: {len(confirmed)} подтверждённых из {len(results)} проверенных")
    for v in confirmed:
        plat = '+'.join(v['platforms'])
        log(f"  score={v['hype_score']} | {plat} | {v.get('views_str','')} | {v.get('title','')[:50]}")

    # 5. Сохраняем
    with open(OUTPUT, 'w') as f:
        json.dump(confirmed, f, ensure_ascii=False, indent=2)
    log(f"Сохранено: {OUTPUT} ({len(confirmed)} видео)")

    # Также выводим все результаты (включая не подтверждённые) для отладки
    print(json.dumps({
        'total_checked': len(results),
        'confirmed': len(confirmed),
        'sound_viral': len([r for r in results if r.get('sound_viral')]),
        'scores': {
            '1_tiktok_only': len([r for r in results if r['hype_score'] == 1]),
            '2_tiktok_youtube': len([r for r in results if r['hype_score'] == 2]),
            '3_triple': len([r for r in results if r['hype_score'] == 3]),
            '4_quad': len([r for r in results if r['hype_score'] == 4]),
        }
    }))

if __name__ == '__main__':
    main()
