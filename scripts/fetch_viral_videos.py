#!/usr/bin/env python3
"""
Вирусные видео/тренды за последний месяц.
Источники: YouTube (scrapetube) + Reddit + Google Trends RSS
Фильтр: VPD >= 300K
"""
import subprocess, json, re, sys
from datetime import datetime

try:
    import scrapetube
    HAS_SCRAPETUBE = True
except:
    HAS_SCRAPETUBE = False

OUT_FILE = '/tmp/viral_videos.json'
MIN_VPD = 300_000

# ── утилиты ────────────────────────────────────────────────────────────────

def parse_views(text):
    if not text: return 0
    t = str(text).replace(',', '').replace(' views', '').replace(' просм.', '').strip()
    try:
        if 'K' in t: return int(float(t.replace('K', '')) * 1_000)
        if 'M' in t: return int(float(t.replace('M', '')) * 1_000_000)
        if 'B' in t: return int(float(t.replace('B', '')) * 1_000_000_000)
        return int(t)
    except: return 0

def age_days(text):
    if not text: return 30
    t = str(text).lower()
    try:
        n = int(''.join(filter(str.isdigit, t)) or '1')
        if 'hour' in t: return max(1, n // 24)
        if 'day'  in t: return n
        if 'week' in t: return n * 7
        if 'month'in t: return n * 30
        if 'year' in t: return n * 365
    except: pass
    return 30

def grade(vpd):
    if vpd >= 5_000_000: return "🔥🔥"
    if vpd >= 1_000_000: return "🔥"
    if vpd >= 500_000:   return "🚀🔥"
    if vpd >= 300_000:   return "🚀"
    return "⚡"

def fmt_views(v):
    if v >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:     return f"{v/1_000_000:.1f}M"
    return f"{v//1000}K"

def dur_secs(text):
    if not text: return None
    parts = text.strip().split(':')
    try:
        if len(parts) == 2: return int(parts[0])*60 + int(parts[1])
        if len(parts) == 3: return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
    except: pass
    return None

# ── 1. YouTube (scrapetube) ────────────────────────────────────────────────

QUERIES = [
    # Игровые механики и челленджи
    'viral game challenge 2026',
    'squid game viral 2026',
    'viral mobile game 2026',
    'addictive game 2026 million views',
    'satisfying game viral 2026',
    'hypercasual game viral 2026',
    'this game is taking over 2026',
    'viral puzzle game 2026',
    # TikTok тренды которые стали играми
    'tiktok challenge game 2026 viral',
    'viral tiktok game trend 2026',
    # YouTube Gaming тренды
    'gaming viral youtube 2026',
    'new viral game gameplay 2026',
    'indie game going viral 2026',
    'mobile game everyone playing 2026',
    # Шортсы
    'viral game shorts 2026 million views',
    'addictive game shorts 2026',
    # Другие языки (больше охват)
    'вирусная игра 2026 миллион просмотров',
    'jogo viral 2026',  # португальский (BR)
]

results = []
seen = set()

if HAS_SCRAPETUBE:
    print(f"YouTube: {len(QUERIES)} запросов...", file=sys.stderr)
    for q in QUERIES:
        try:
            vids = list(scrapetube.get_search(q, limit=20, sleep=0.2))
            for v in vids:
                vid_id = v.get('videoId', '')
                if vid_id in seen: continue

                # Просмотры
                views_raw = v.get('viewCountText', {})
                views_text = views_raw.get('simpleText', '') if isinstance(views_raw, dict) else ''
                views = parse_views(views_text)
                if views < 300_000: continue  # пре-фильтр

                # Дата
                pub_raw = v.get('publishedTimeText', {})
                pub_text = pub_raw.get('simpleText', '') if isinstance(pub_raw, dict) else ''
                age = age_days(pub_text)
                if age > 45: continue  # только последние 45 дней

                vpd = views // max(age, 1)
                if vpd < MIN_VPD: continue

                title = v.get('title', {}).get('runs', [{}])[0].get('text', '')
                channel = v.get('longBylineText', {}).get('runs', [{}])[0].get('text', '')

                # Фильтр нерелевантного контента
                title_low = title.lower()
                channel_low = channel.lower()
                skip_words = ['news', 'broadcast', 'episode', 'sermon', 'church',
                              'prayer', 'nigerian', 'nollywood', 'brahmachari',
                              'muir', 'abc world', 'full episode', 'cbs', 'nbc news',
                              'fox news', 'cnn', 'msnbc', 'bbc', 'god of wonders',
                              'jesus', 'allah', 'pastor', 'wrestling', 'wwe', 'raw highlights',
                              'trailer netflix', 'trailer amazon', 'official trailer']
                if any(w in title_low or w in channel_low for w in skip_words):
                    continue

                seen.add(vid_id)
                length_text = v.get('lengthText', {}).get('simpleText', '')
                d = dur_secs(length_text)
                is_short = d is not None and d <= 62

                results.append({
                    'source': 'youtube',
                    'kind': 'Short' if is_short else 'Video',
                    'title': title,
                    'channel': channel,
                    'views': views,
                    'views_str': fmt_views(views),
                    'age_days': age,
                    'vpd': vpd,
                    'grade': grade(vpd),
                    'url': f'https://youtu.be/{vid_id}',
                    'thumb': f'https://img.youtube.com/vi/{vid_id}/mqdefault.jpg',
                    'published': pub_text,
                })
        except Exception as e:
            print(f"  skip '{q}': {e}", file=sys.stderr)

    print(f"  YouTube: {len(results)} видео >= {MIN_VPD:,} VPD", file=sys.stderr)

# ── 2. Reddit ──────────────────────────────────────────────────────────────

print("Reddit топ недели...", file=sys.stderr)
reddit_count = 0
for sub in ['gaming', 'games', 'videos']:
    try:
        out = subprocess.check_output(
            f'curl -sL "https://www.reddit.com/r/{sub}/top.json?t=week&limit=25" '
            f'-H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" '
            f'-H "Accept: application/json" --compressed',
            shell=True, timeout=15)
        data = json.loads(out)
        posts = data.get('data', {}).get('children', [])
        for p in posts:
            d = p.get('data', {})
            ups = d.get('ups', 0)
            if ups < 30_000: continue
            title = d.get('title', '')
            permalink = 'https://reddit.com' + d.get('permalink', '')
            created = d.get('created_utc', 0)
            age = max(1, int((datetime.now().timestamp() - created) / 86400))
            thumb = d.get('thumbnail', '')
            if not thumb.startswith('http'): thumb = ''
            results.append({
                'source': f'reddit/r/{sub}',
                'kind': 'Post',
                'title': title,
                'channel': f'r/{sub} · {ups:,} upvotes',
                'views': ups * 50,  # upvotes → ~views estimate
                'views_str': f'{ups:,} upvotes',
                'age_days': age,
                'vpd': ups // age,
                'grade': '🔥' if ups > 100_000 else '🚀',
                'url': permalink,
                'thumb': thumb,
                'published': f'{age}д назад',
            })
            reddit_count += 1
    except Exception as e:
        print(f"  Reddit r/{sub}: {e}", file=sys.stderr)

print(f"  Reddit: {reddit_count} постов", file=sys.stderr)

# ── 3. Google Trends RSS ───────────────────────────────────────────────────

print("Google Trends...", file=sys.stderr)
trends_count = 0
try:
    rss = subprocess.check_output(
        'curl -sL "https://trends.google.com/trending/rss?geo=US" -H "User-Agent: Mozilla/5.0"',
        shell=True, timeout=10).decode('utf-8', errors='ignore')
    items = re.findall(r'<title><!\[CDATA\[([^\]]+)\]\]></title>', rss)
    if not items:
        items = re.findall(r'<ht:approx_traffic>([^<]+)</ht:approx_traffic>', rss)
        titles = re.findall(r'<title>([^<]+)</title>', rss)[1:]
        items = titles
    for trend in items[:20]:
        trend = trend.strip()
        if len(trend) < 3: continue
        results.append({
            'source': 'google_trends',
            'kind': 'Trend',
            'title': trend,
            'channel': 'Google Trends US',
            'views': 0,
            'views_str': '🔥 Trending',
            'age_days': 1,
            'vpd': 0,
            'grade': '🔥',
            'url': f'https://trends.google.com/trends/explore?q={trend.replace(" ", "+")}',
            'thumb': '',
            'published': 'сейчас',
        })
        trends_count += 1
    print(f"  Google Trends: {trends_count} трендов", file=sys.stderr)
except Exception as e:
    print(f"  Trends error: {e}", file=sys.stderr)

# ── сортировка ─────────────────────────────────────────────────────────────

yt_reddit = [r for r in results if r['source'] != 'google_trends']
trends    = [r for r in results if r['source'] == 'google_trends']

# дедупликация
seen2 = set()
yt_reddit_u = []
for r in yt_reddit:
    key = r['url']
    if key not in seen2:
        seen2.add(key)
        yt_reddit_u.append(r)

yt_reddit_u.sort(key=lambda x: x['vpd'], reverse=True)

final = yt_reddit_u[:25] + trends[:15]

print(f"\n🔥 Топ вирусных:\n", file=sys.stderr)
for r in yt_reddit_u[:12]:
    k = '🩳' if r['kind'] == 'Short' else ('📋' if r['kind'] == 'Post' else '▶')
    print(f"  {k} {r['grade']} {r['vpd']:>10,}/д | {r['views_str']:>8} | {r['title'][:52]}", file=sys.stderr)

with open(OUT_FILE, 'w') as f:
    json.dump(final, f, ensure_ascii=False, indent=2)

print(f"\nСохранено: {OUT_FILE} ({len(final)} записей: {len(yt_reddit_u)} видео + {len(trends)} трендов)", file=sys.stderr)
print(json.dumps({'count': len(final), 'videos': len(yt_reddit_u), 'trends': len(trends)}))
