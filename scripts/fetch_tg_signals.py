#!/usr/bin/env python3
"""
Сигналы из Telegram-каналов о трендах/мемах.
Читает посты → извлекает ключевые слова → ищет видео на YouTube.

Каналы: memolodjiya (и другие похожие)
Результат: /tmp/tg_signals.json
"""
import subprocess, json, sys, re, time, urllib.request
from datetime import datetime

YT_DLP = '/opt/homebrew/bin/yt-dlp'
OUT_FILE = '/tmp/tg_signals.json'

# Telegram каналы-радары
TG_CHANNELS = [
    'memolodjiya',   # истории мемов, вирусные тренды TikTok
    'internetculture',  # западные интернет-тренды
]

# Ключевые слова что нам интересно
INTEREST_KEYWORDS = [
    'вирусит', 'хайп', 'тренд', 'набирает', 'популярн', 'вирус',
    'tiktok', 'тикток', 'youtube', 'ютуб',
    'игра', 'game', 'мем',
    'viral', 'trending', 'blew up',
]

# Стоп-слова (не ищем по ним)
STOP_WORDS = [
    'скам', 'взломали', 'реклама', 'конкурс', 'подпиш', 'донат',
    'криптo', 'токен', 'инвест', 'ставк',
]

MAX_AGE_DAYS_POST = 7   # посты не старше 7 дней
MIN_VIEWS_YT = 10_000   # минимум просмотров на YouTube
MAX_YT_RESULTS = 5      # видео на поисковый запрос


def fmt_views(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(v)


def fetch_tg_posts(channel):
    """Парсит последние посты из публичного Telegram канала."""
    try:
        req = urllib.request.Request(
            f'https://t.me/s/{channel}',
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  [{channel}] fetch error: {e}", file=sys.stderr)
        return []

    posts = []
    blocks = re.split(r'tgme_widget_message_wrap', html)
    for block in blocks[1:]:
        # Текст поста
        text_m = re.search(r'js-message_text[^>]*>(.+?)(?:</div>\s*){2}', block, re.S)
        if not text_m:
            continue
        text = re.sub('<[^>]+>', '', text_m.group(1)).strip()
        text = re.sub(r'\s+', ' ', text)

        if len(text) < 20:
            continue

        # Дата (если есть)
        date_m = re.search(r'datetime="([^"]+)"', block)
        post_date = date_m.group(1) if date_m else None

        # Ссылка на пост
        link_m = re.search(rf't\.me/{channel}/(\d+)', block)
        post_id = link_m.group(1) if link_m else None

        # Просмотры поста
        views_m = re.search(r'message_views[^>]*>([^<]+)', block)
        post_views = views_m.group(1).strip() if views_m else '?'

        posts.append({
            'channel': channel,
            'text': text,
            'date': post_date,
            'post_id': post_id,
            'post_views': post_views,
            'url': f'https://t.me/{channel}/{post_id}' if post_id else f'https://t.me/{channel}',
        })

    return posts


def extract_topic(text):
    """Извлекает ключевую тему из текста поста для поиска на YouTube."""
    text_lower = text.lower()

    # Проверяем стоп-слова
    for sw in STOP_WORDS:
        if sw in text_lower:
            return None

    # Проверяем интересные слова
    is_interesting = any(kw in text_lower for kw in INTEREST_KEYWORDS)
    if not is_interesting:
        return None

    # Ищем конкретную тему в кавычках
    quoted = re.findall(r'[«"\'"]([^»"\'"\n]{3,50})[»"\'"]', text)
    if quoted:
        # Берём первую цитату которая не слишком короткая
        for q in quoted:
            if len(q) > 5 and not any(sw in q.lower() for sw in STOP_WORDS):
                return q.strip()

    # Ищем паттерны "мем/тренд: НАЗВАНИЕ"
    patterns = [
        r'(?:тренд|мем|хайп|вирусится|вирусный)[:\s]+[«"]?([А-Яа-яA-Za-z0-9 \-]{4,40})',
        r'(?:trend|meme|viral)[:\s]+["\']?([A-Za-z0-9 \-]{4,40})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            topic = m.group(1).strip().rstrip('"\'»')
            if len(topic) > 3:
                return topic

    return None


def search_youtube(query, max_results=MAX_YT_RESULTS):
    """Ищет видео на YouTube через scrapetube."""
    try:
        import scrapetube
        vids = list(scrapetube.get_search(query, limit=max_results, sleep=0.3))
        results = []
        for v in vids:
            vid_id = v.get('videoId', '')
            if not vid_id:
                continue
            title = v.get('title', {}).get('runs', [{}])[0].get('text', '')
            views_text = v.get('viewCountText', {}).get('simpleText', '') if isinstance(v.get('viewCountText'), dict) else ''
            results.append({
                'id': vid_id,
                'title': title,
                'views_text': views_text,
                'url': f'https://youtu.be/{vid_id}',
                'thumb': f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg',
            })
        return results
    except ImportError:
        print("  scrapetube не установлен", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  YouTube search error: {e}", file=sys.stderr)
        return []


# ── Main ──

print("Сбор сигналов из Telegram...", file=sys.stderr)

all_signals = []

for channel in TG_CHANNELS:
    print(f"  Читаю @{channel}...", file=sys.stderr)
    posts = fetch_tg_posts(channel)
    print(f"    {len(posts)} постов", file=sys.stderr)

    for post in posts:
        topic = extract_topic(post['text'])
        if not topic:
            continue

        print(f"    💡 Тема: {topic[:50]}", file=sys.stderr)

        # Ищем на YouTube
        yt_results = search_youtube(topic + ' viral 2026', max_results=3)
        if not yt_results:
            yt_results = search_youtube(topic, max_results=3)

        signal = {
            'source': 'tg_signal',
            'tg_channel': channel,
            'tg_post_url': post['url'],
            'tg_text': post['text'][:300],
            'topic': topic,
            'youtube_videos': yt_results,
            'detected_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
        all_signals.append(signal)
        time.sleep(0.5)

print(f"\nИтого сигналов: {len(all_signals)}", file=sys.stderr)
for s in all_signals:
    yt_count = len(s['youtube_videos'])
    print(f"  [{s['tg_channel']}] {s['topic'][:40]} → {yt_count} YouTube видео", file=sys.stderr)

with open(OUT_FILE, 'w') as f:
    json.dump(all_signals, f, ensure_ascii=False, indent=2)

print(json.dumps({'count': len(all_signals)}))
