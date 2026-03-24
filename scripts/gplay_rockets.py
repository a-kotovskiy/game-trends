#!/usr/bin/env python3
"""Находит 'ракеты' в Google Play - новые игры с быстрым ростом.
Стратегия многоуровневая:
1. Страницы категорий (10 категорий × 5 регионов)
2. Поиск через google-play-scraper search по запросам новинок
3. Фильтрация по дате (≤30 дней) + dl/day
"""
import subprocess, re, argparse, sys, json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from google_play_scraper import app as gps_app, search as gps_search, reviews as gps_reviews, Sort
    HAS_GPS = True
except ImportError:
    HAS_GPS = False
    print("WARN: google-play-scraper not installed", file=sys.stderr)

parser = argparse.ArgumentParser()
parser.add_argument('--days', type=int, default=30)
parser.add_argument('--min-dpd', type=int, default=1000)
parser.add_argument('--limit', type=int, default=10)
parser.add_argument('--json', action='store_true')
args = parser.parse_args()

UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
HEADERS = f'-H "User-Agent: {UA}" -H "Accept-Language: en-US,en;q=0.9"'

# Регионы: US + ключевые рынки где ракеты взлетают раньше
REGIONS = ['us', 'ru', 'br', 'in', 'de', 'gb', 'tr', 'id']

# Коллекции для парсинга чартов
COLLECTIONS = ['topselling_free', 'topselling_new_free', 'topgrossing']

# Все игровые категории Google Play
CATEGORIES = [
    'GAME_ACTION', 'GAME_CASUAL', 'GAME_ARCADE', 'GAME_PUZZLE',
    'GAME_RACING', 'GAME_STRATEGY', 'GAME_ROLE_PLAYING', 'GAME_SIMULATION',
    'GAME_SPORTS', 'GAME_ADVENTURE', 'GAME_BOARD', 'GAME_CARD',
    'GAME_TRIVIA', 'GAME_WORD', 'GAME_EDUCATIONAL', 'GAME_MUSIC',
]

# Поисковые запросы для нахождения новинок через search API
SEARCH_QUERIES = [
    ('new mobile game 2026', 'us'),
    ('new game march 2026', 'us'),
    ('new game february 2026', 'us'),
    ('new casual game 2026', 'us'),
    ('new rpg mobile game 2026', 'us'),
    ('new action game 2026', 'us'),
    ('new puzzle game 2026', 'us'),
    ('new strategy game 2026', 'us'),
    ('new simulation game 2026', 'us'),
    ('new idle game 2026', 'us'),
    ('new survival game android 2026', 'us'),
    ('новая игра 2026', 'ru'),
    ('released 2026', 'us'),
    ('new game 2026', 'in'),
    ('new game 2026', 'br'),
    ('new game 2026', 'de'),
    ('new game 2026', 'gb'),
    ('new game 2026', 'tr'),
    ('new game 2026', 'id'),
    ('new game 2026', 'ru'),
    ('just released game android', 'us'),
    ('best new free game android 2026', 'us'),
    ('viral mobile game 2026', 'us'),
    ('trending mobile game 2026', 'us'),
    ('new hyper casual game 2026', 'us'),
    # Ниши которые часто дают ракеты
    ('idle game new', 'us'),
    ('merge game 2026', 'us'),
    ('puzzle game new release', 'us'),
    ('hypercasual game new', 'us'),
    ('clicker game new', 'us'),
    ('shooting game new', 'us'),
    ('runner game new', 'us'),
    ('survival game new', 'us'),
    # Roblox-style
    ('obby game', 'us'),
    ('parkour game mobile', 'us'),
    # Виральные жанры
    ('brainrot game', 'us'),
    ('skibidi game', 'us'),
    ('satisfying game', 'us'),
    ('asmr game', 'us'),
    # Доп жанры и тренды
    ('tycoon game new 2026', 'us'),
    ('horror game mobile 2026', 'us'),
    ('escape game new android', 'us'),
    ('tower defense new 2026', 'us'),
    ('roguelike mobile new', 'us'),
    ('vampire survivors like', 'us'),
    ('anime game new 2026', 'us'),
    ('cooking game new 2026', 'us'),
    ('farming game new 2026', 'us'),
    ('zombie game new 2026', 'us'),
    ('car game new 2026', 'us'),
    ('FPS game new android', 'us'),
    ('battle royale new 2026', 'us'),
    ('card game new android 2026', 'us'),
    ('base building game new', 'us'),
    ('sandbox game new android', 'us'),
    ('multiplayer game new 2026', 'us'),
    ('offline game new 2026', 'us'),
    # Регионы с активным мобайлом
    ('new game 2026', 'jp'),
    ('new game 2026', 'kr'),
    ('new game 2026', 'mx'),
    ('new game 2026', 'ph'),
    ('new game 2026', 'th'),
]

SKIP_KEYWORDS = [
    'google', 'android', 'http', 'www', 'gstatic', 'youtube', 'firebase',
    'crashlytics', 'adjust', 'appsflyer', 'facebook', 'unity', 'amazon',
    'admob', 'chartboost', 'mopub', 'flurry'
]

def get_ids_from_url(url):
    try:
        cmd = f'curl -sL "{url}" {HEADERS}'
        html = subprocess.check_output(cmd, shell=True, timeout=20).decode('utf-8', errors='ignore')
        ids = re.findall(r'"([a-z][a-zA-Z0-9]*\.[a-zA-Z][a-zA-Z0-9.]{3,})"', html)
        clean = [i for i in ids if '.' in i and not any(x in i for x in SKIP_KEYWORDS)]
        return list(set(clean))
    except:
        return []

def get_ids_from_search(query, country):
    try:
        results = gps_search(query, n_hits=30, lang='en', country=country)
        return [r['appId'] for r in results]
    except:
        return []

def get_reviews_by_day(app_id, release_date_str=None):
    """Получает ВСЕ отзывы с даты релиза через пагинацию."""
    if not HAS_GPS:
        return []
    try:
        from collections import Counter
        # Определяем дату релиза как нижнюю границу
        cutoff = None
        if release_date_str:
            rel = parse_date(release_date_str)
            if rel:
                cutoff = rel.date()

        all_reviews = []
        token = None
        max_pages = 20  # максимум страниц (20 × 200 = 4000 отзывов)
        for _ in range(max_pages):
            result, token = gps_reviews(app_id, lang='en', country='us',
                                        sort=Sort.NEWEST, count=200,
                                        continuation_token=token)
            if not result:
                break
            all_reviews.extend(result)
            # Если самый старый отзыв раньше релиза - достаточно
            oldest = min(r['at'] for r in result if r.get('at'))
            if not token or (cutoff and oldest.date() < cutoff):
                break

        day_counts = Counter()
        for r in all_reviews:
            d = r.get('at')
            if d:
                if cutoff and d.date() < cutoff:
                    continue
                day_counts[d.strftime('%Y-%m-%d')] += 1

        return [{"date": d, "count": day_counts[d]} for d in sorted(day_counts.keys())]
    except:
        return []

def get_app_data(app_id):
    if not HAS_GPS:
        return None
    try:
        r = gps_app(app_id, lang='en', country='us')
        if not r.get('released'):
            return None
        real = r.get('realInstalls', 0) or 0
        installs_str = r.get('installs', '0+')
        if real >= 1_000_000_000:
            dl_str_real = f"{real/1_000_000_000:.1f}B"
        elif real >= 1_000_000:
            dl_str_real = f"{real/1_000_000:.1f}M"
        elif real >= 1_000:
            dl_str_real = f"{real/1_000:.0f}K"
        else:
            dl_str_real = str(real)
        screens = [s + '=w300' for s in (r.get('screenshots') or [])[:4]]
        return {
            'id': app_id,
            'title': r['title'],
            'icon': r.get('icon', ''),
            'screenshots': screens,
            'downloads': real if real > 0 else _parse_installs(installs_str),
            'dl_str': installs_str,
            'dl_str_real': dl_str_real,
            'released': r['released'],
            'genre': r.get('genre', ''),
            'score': round(r['score'], 1) if r.get('score') else None,
            'ratings': r.get('ratings', 0),
            'developer': r.get('developer', ''),
            'summary': r.get('summary', ''),
            'contentRating': r.get('contentRating', ''),
            'offersIAP': r.get('offersIAP', False),
            'lastUpdated': r.get('lastUpdatedOn', ''),
        }
    except Exception:
        return None

def _parse_installs(s):
    mapping = {
        '1,000,000,000+': 1_000_000_000, '500,000,000+': 500_000_000,
        '100,000,000+': 100_000_000, '50,000,000+': 50_000_000,
        '10,000,000+': 10_000_000, '5,000,000+': 5_000_000,
        '1,000,000+': 1_000_000, '500,000+': 500_000,
        '100,000+': 100_000, '50,000+': 50_000,
        '10,000+': 10_000, '5,000+': 5_000, '1,000+': 1_000,
    }
    return mapping.get(s, 0)

def parse_date(s):
    for fmt in ("%b %d, %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except:
            pass
    return None

def get_similar_apps(app_ids, max_per_app=10):
    """Берёт похожие игры для топ ракет — там часто новинки той же ниши."""
    import time as _time
    similar_ids = set()
    for app_id in app_ids[:5]:
        try:
            details = gps_app(app_id, lang='en', country='us')
            genre = details.get('genre', '')
            if genre:
                results = gps_search(f"{genre} new 2026", n_hits=max_per_app, country='us', lang='en')
                for r in results:
                    aid = r.get('appId', '')
                    if aid:
                        similar_ids.add(aid)
            _time.sleep(0.3)
        except Exception:
            pass
    return similar_ids

def score_rocket(data):
    if not data or not data.get('released'):
        return None
    rel = parse_date(data['released'])
    if not rel:
        return None
    days = (datetime.now() - rel).days
    if days < 1 or days > args.days:
        return None
    dl_per_day = (data['downloads'] or 0) / days if days > 0 else 0

    # Для watchlist-игр (уже известных) показывать если dpd >= 100
    is_watchlist = data['id'] in _auto_watchlist_ids

    # Интересная новинка: ≤3 дня, ≥10K установок, рейтинг ≥4.0 — включаем вне зависимости от dpd
    is_interesting_newcomer = (
        days <= 3
        and (data['downloads'] or 0) >= 10_000
        and (data.get('score') or 0) >= 4.0
    )

    # Адаптивный порог: молодые игры (≤7 дней) получают сниженный порог
    if is_watchlist:
        threshold = 100
    elif is_interesting_newcomer:
        threshold = 0  # пропускаем любой dpd
    elif days <= 7:
        threshold = 500  # сниженный порог для молодых игр
    else:
        threshold = args.min_dpd

    if dl_per_day < threshold:
        return None
    data['days'] = days
    data['dl_per_day'] = dl_per_day
    data['is_newcomer'] = is_interesting_newcomer
    if dl_per_day >= 100000:
        data['grade'] = "🚀🔥"
    elif dl_per_day >= 20000:
        data['grade'] = "🚀"
    elif dl_per_day >= 5000:
        data['grade'] = "⚡"
    else:
        data['grade'] = "📈"
    return data

# === СБОР IDs ===
all_ids = set()

# 1. Страницы категорий × регионы × коллекции (параллельно)
urls = []
for cat in CATEGORIES:
    for region in REGIONS:
        # Страница категории (общая)
        urls.append(f"https://play.google.com/store/apps/category/{cat}?hl=en&gl={region}")
        # Коллекции внутри категории
        for col in COLLECTIONS:
            urls.append(f"https://play.google.com/store/apps/category/{cat}/collection/{col}?hl=en&gl={region}")
# + главная по регионам и коллекции
for region in REGIONS:
    urls.append(f"https://play.google.com/store/games?hl=en&gl={region}")
    for col in COLLECTIONS:
        urls.append(f"https://play.google.com/store/games/collection/{col}?hl=en&gl={region}")

print(f"Собираю ids с {len(urls)} страниц...", file=sys.stderr)
with ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(get_ids_from_url, url): url for url in urls}
    for fut in as_completed(futures):
        ids = fut.result()
        before = len(all_ids)
        all_ids.update(ids)
        if len(all_ids) > before:
            pass  # молча
print(f"После категорий: {len(all_ids)} уникальных ids", file=sys.stderr)

# 1.5. Внешние агрегаторы (AppBrain, AndroidRank и т.д.)
EXTERNAL_URLS = [
    # AppBrain - новинки, растущие, популярные бесплатные игры
    "https://www.appbrain.com/stats/new-android-games",
    "https://www.appbrain.com/stats/google-play-rankings/top_free/game",
    "https://www.appbrain.com/stats/google-play-rankings/top_growing/game",
    "https://www.appbrain.com/stats/google-play-rankings/top_new_free/game",
    "https://www.appbrain.com/stats/google-play-rankings/topselling_new_free/game",
    # AndroidRank - недавние хиты
    "https://androidrank.org/android-most-popular-google-play-apps?category=GAME&sort=4&price=free",
    "https://androidrank.org/android-most-popular-google-play-apps?category=GAME&sort=0&price=free",
    # Google Play top charts прямые ссылки (больше регионов)
    "https://play.google.com/store/games/collection/cluster?clp=0g4jCiEKG3RvcHNlbGxpbmdfZnJlZV9HQU1FX0FMTBAHUA%3D%3D:S:ANO1ljKcVIA&gsr=CibSDiMKIQobdG9wc2VsbGluZ19mcmVlX0dBTUVfQUxMEFBYAQ%3D%3D:S:ANO1ljIKCfQ",
    "https://play.google.com/store/games/collection/cluster?clp=0g4nCiUKH3RvcHNlbGxpbmdfbmV3X2ZyZWVfR0FNRV9BTEwQUFgB:S:ANO1ljJIvJw&gsr=CirSDicKJQofdG9wc2VsbGluZ19uZXdfZnJlZV9HQU1FX0FMTBBQWAE%3D:S:ANO1ljIiVng",
    # SimilarWeb top apps (если доступно)
    "https://www.similarweb.com/apps/top/google/store-rank/us/games/top-free/",
    "https://www.similarweb.com/apps/top/google/store-rank/us/games/new-apps/",
]

def get_ids_from_external(url):
    """Парсит app ids из внешних агрегаторов."""
    try:
        cmd = f'curl -sL "{url}" -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36" --connect-timeout 10 --max-time 20'
        html = subprocess.check_output(cmd, shell=True, timeout=25).decode('utf-8', errors='ignore')
        # Ищем Google Play app ids в ссылках и тексте
        ids = re.findall(r'(?:id=|details\?id=|/app/)([a-z][a-zA-Z0-9]*\.[a-zA-Z][a-zA-Z0-9.]{3,})', html)
        # Также парсим стандартный формат пакетов
        ids += re.findall(r'"([a-z][a-zA-Z0-9]*\.[a-zA-Z][a-zA-Z0-9.]{3,})"', html)
        clean = [i for i in ids if '.' in i and not any(x in i for x in SKIP_KEYWORDS)]
        return list(set(clean))
    except:
        return []

print(f"Внешние агрегаторы ({len(EXTERNAL_URLS)} URL)...", file=sys.stderr)
before_ext = len(all_ids)
with ThreadPoolExecutor(max_workers=6) as ex:
    futures = {ex.submit(get_ids_from_external, url): url for url in EXTERNAL_URLS}
    for fut in as_completed(futures):
        ids = fut.result()
        all_ids.update(ids)
print(f"После агрегаторов: +{len(all_ids) - before_ext} новых, итого {len(all_ids)}", file=sys.stderr)

# 2. Поиск через search API (параллельно) - их ставим в приоритет
print(f"Поиск через search API ({len(SEARCH_QUERIES)} запросов)...", file=sys.stderr)
search_ids = set()
with ThreadPoolExecutor(max_workers=5) as ex:
    futures = {ex.submit(get_ids_from_search, q, c): (q, c) for q, c in SEARCH_QUERIES}
    for fut in as_completed(futures):
        ids = fut.result()
        search_ids.update(ids)
        all_ids.update(ids)
print(f"После search: {len(all_ids)} уникальных ids", file=sys.stderr)

# 3. Похожие игры на топ из поиска (ищем новинки той же ниши)
if HAS_GPS and search_ids:
    print(f"Ищу похожие игры для топ из поиска...", file=sys.stderr)
    similar = get_similar_apps(list(search_ids))
    before_similar = len(all_ids)
    all_ids.update(similar)
    print(f"Похожие игры: +{len(all_ids) - before_similar} новых ids", file=sys.stderr)

# Авто-вотчлист: все игры которые мы когда-либо находили
import json as _json, os as _os
_history_file = _os.path.join(_os.path.dirname(__file__), '../dashboard/all_rockets_history.json')
_auto_watchlist_ids = set()
if _os.path.exists(_history_file):
    try:
        _hist = _json.load(open(_history_file))
        _auto_watchlist_ids = set(_hist.keys())
        all_ids.update(_auto_watchlist_ids)
        print(f"Авто-вотчлист из истории: {len(_auto_watchlist_ids)} игр", file=sys.stderr)
    except:
        pass

# Добавляем watchlist - игры которые всегда проверяем
_watchlist_path = _os.path.join(_os.path.dirname(__file__), 'watchlist.json')
if _os.path.exists(_watchlist_path):
    try:
        _wl = _json.load(open(_watchlist_path))
        _wl_ids = _wl.get('apps', [])
        for _wid in _wl_ids:
            all_ids.add(_wid)
        print(f"Watchlist: добавлено {len(_wl_ids)} игр", file=sys.stderr)
    except Exception as _e:
        print(f"Watchlist ошибка: {_e}", file=sys.stderr)

# Search ids первыми, потом watchlist, потом остальные - без лимита
priority_ids = list(search_ids) + [i for i in all_ids if i not in search_ids]
ids_list = priority_ids  # проверяем все
print(f"Проверяю {len(ids_list)} игр (search-приоритет, 20 потоков)...", file=sys.stderr)

# === ФИЛЬТРАЦИЯ ПО ДАТЕ И DL/DAY ===
rockets = []

def process_id(aid):
    data = get_app_data(aid)
    rocket = score_rocket(data)
    if rocket:
        rocket['reviewsByDay'] = get_reviews_by_day(aid, rocket.get('released'))
    return rocket

with ThreadPoolExecutor(max_workers=20) as ex:
    futures = {ex.submit(process_id, aid): aid for aid in ids_list}
    done = 0
    for fut in as_completed(futures):
        done += 1
        r = fut.result()
        if r:
            rockets.append(r)
        if done % 50 == 0:
            print(f"  {done}/{len(ids_list)}, ракет: {len(rockets)}...", file=sys.stderr)

rockets.sort(key=lambda x: x['dl_per_day'], reverse=True)
print(f"Итого ракет: {len(rockets)}", file=sys.stderr)

# === ОБНОВЛЕНИЕ ИСТОРИИ И ТРЕНДЫ ===
def update_history(rockets):
    from datetime import date as _date
    history_file = _os.path.join(_os.path.dirname(__file__),
                                "../dashboard/all_rockets_history.json")
    history = {}
    if _os.path.exists(history_file):
        try:
            with open(history_file) as f:
                history = _json.load(f)
        except:
            pass

    today = str(_date.today())

    for r in rockets:
        app_id = r.get('id', '')
        if not app_id:
            continue
        dpd = int(r.get('dl_per_day', 0))
        installs = r.get('downloads', 0)
        score = r.get('score') or 0

        if app_id not in history:
            history[app_id] = {
                "id": app_id,
                "name": r.get('title', ''),
                "genre": r.get('genre', ''),
                "icon": r.get('icon', ''),
                "url": f"https://play.google.com/store/apps/details?id={app_id}",
                "first_seen": today,
                "last_seen": today,
                "peak_dpd": dpd,
                "peak_date": today,
                "history": []
            }
        else:
            history[app_id]["last_seen"] = today
            history[app_id]["name"] = r.get('title', '') or history[app_id]["name"]
            history[app_id]["icon"] = r.get('icon', '') or history[app_id]["icon"]
            if dpd > history[app_id].get("peak_dpd", 0):
                history[app_id]["peak_dpd"] = dpd
                history[app_id]["peak_date"] = today

        day_history = history[app_id]["history"]
        if not day_history or day_history[-1]["date"] != today:
            day_history.append({
                "date": today,
                "installs": installs,
                "dpd": dpd,
                "score": score
            })
            history[app_id]["history"] = day_history[-90:]

    with open(history_file, "w") as f:
        _json.dump(history, f, ensure_ascii=False, indent=2)

    return history

def add_trends(rockets, history):
    from datetime import date as _date
    today = str(_date.today())
    for r in rockets:
        app_id = r.get('id', '')
        h = history.get(app_id)
        if not h or not h.get('history'):
            r['trend'] = 'new'
            r['dpd_prev'] = 0
            r['dpd_change_pct'] = 0
            continue

        if h.get('first_seen') == today:
            r['trend'] = 'new'
            r['dpd_prev'] = 0
            r['dpd_change_pct'] = 0
            continue

        hist = h['history']
        dpd_now = int(r.get('dl_per_day', 0))
        # Найти предыдущий день (не сегодня)
        dpd_prev = 0
        for entry in reversed(hist):
            if entry['date'] != today:
                dpd_prev = entry.get('dpd', 0)
                break

        r['dpd_prev'] = dpd_prev
        if dpd_prev > 0:
            change = (dpd_now - dpd_prev) / dpd_prev
            r['dpd_change_pct'] = round(change * 100)
            if dpd_now > dpd_prev * 1.1:
                r['trend'] = 'rising'
            elif dpd_now < dpd_prev * 0.9:
                r['trend'] = 'falling'
            else:
                r['trend'] = 'stable'
        else:
            r['dpd_change_pct'] = 0
            r['trend'] = 'new'

history = update_history(rockets)
add_trends(rockets, history)
print(f"История обновлена: {len(history)} игр всего", file=sys.stderr)

# === ВЫВОД ===
if args.json:
    # Загружаем историю dpd для графиков
    _dpd_history = {}
    try:
        _hist_file = _os.path.join(_os.path.dirname(__file__), '../dashboard/all_rockets_history.json')
        if _os.path.exists(_hist_file):
            with open(_hist_file) as _hf:
                _full_hist = _json.load(_hf)
            for _app_id, _hdata in _full_hist.items():
                _dpd_history[_app_id] = [
                    {"date": e["date"], "dpd": e["dpd"], "installs": e.get("installs", 0)}
                    for e in _hdata.get("history", [])
                ]
    except Exception as _he:
        print(f"dpdHistory load error: {_he}", file=sys.stderr)

    # Топ-N по dpd
    top_rockets = rockets[:args.limit]
    top_ids = {r['id'] for r in top_rockets}

    # Watchlist игры которые не попали в топ — добавляем принудительно
    _wl_path = _os.path.join(_os.path.dirname(__file__), 'watchlist.json')
    _wl_ids = []
    try:
        with open(_wl_path) as _wf:
            _wl_ids = _json.load(_wf).get('apps', [])
    except: pass

    extra_watchlist = [r for r in rockets if r['id'] in _wl_ids and r['id'] not in top_ids]
    output_rockets = top_rockets + extra_watchlist

    def make_rocket_entry(r):
        dpd = int(r['dl_per_day'])
        real = r['downloads'] or 0
        if real >= 1_000_000_000:   tag = "1B+"
        elif real >= 100_000_000:   tag = "100M+"
        elif real >= 10_000_000:    tag = "10M+"
        elif real >= 1_000_000:     tag = "1M+"
        elif real >= 500_000:       tag = "500K+"
        elif real >= 100_000:       tag = "100K+"
        elif real >= 50_000:        tag = "50K+ УСТАНОВОК"
        else:                       tag = "НОВИНКА"
        ratings = r.get('ratings') or 0
        ratings_str = f"{ratings//1000}K" if ratings >= 1000 else str(ratings)
        is_watchlist = r['id'] in _wl_ids
        return {
            "id": r['id'],
            "emoji": r['grade'],
            "tag": tag,
            "name": r['title'],
            "icon": r.get('icon', ''),
            "screenshots": r.get('screenshots', []),
            "genre": r.get('genre', ''),
            "developer": r.get('developer', ''),
            "downloads": r.get('dl_str', ''),
            "realInstalls": real,
            "realInstallsStr": r.get('dl_str_real', ''),
            "perDay": dpd,
            "days": r['days'],
            "score": r.get('score'),
            "ratings": ratings,
            "ratingsStr": ratings_str,
            "contentRating": r.get('contentRating') or '',
            "offersIAP": r.get('offersIAP') or False,
            "releaseDate": r['released'],
            "lastUpdated": r.get('lastUpdated') or '',
            "summary": r.get('summary') or '',
            "url": f"https://play.google.com/store/apps/details?id={r['id']}",
            "reviewsByDay": r.get('reviewsByDay') or [],
            "dpdHistory": _dpd_history.get(r['id'], []),
            "trend": r.get('trend') or 'stable',
            "dpd_prev": r.get('dpd_prev') or 0,
            "dpd_change_pct": r.get('dpd_change_pct') or 0,
            "isWatchlist": is_watchlist
        }

    # Топ - только не-watchlist игры (или watchlist игры которые попали в органический топ)
    top_output = [make_rocket_entry(r) for r in top_rockets if r['id'] not in _wl_ids]
    # Watchlist - все watchlist игры отдельно
    watchlist_output = [make_rocket_entry(r) for r in rockets if r['id'] in _wl_ids]

    result = {"rockets": top_output, "watchlist": watchlist_output}
    print(json.dumps(result, ensure_ascii=False))
else:
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"\n🎮 ХАЙП GOOGLE PLAY — {today}")
    print(f"Новые игры с взрывным ростом (до {args.days} дней, от {args.min_dpd:,} уст./день)\n")
    for r in rockets[:args.limit]:
        dpd = int(r['dl_per_day'])
        real_str = r.get('dl_str_real', r['dl_str'])
        score_str = f" ⭐{r['score']}" if r.get('score') else ""
        ratings = r.get('ratings', 0)
        rat_str = f" ({ratings:,} отзывов)" if ratings else ""
        print(f"{r['grade']} {r.get('genre', '')}")
        print(f"🎮 {r['title']}{score_str}{rat_str}")
        print(f"   📥 {real_str} ({dpd:,}/день) за {r['days']} дн.")
        print(f"   📅 Релиз: {r['released']}")
        print(f"   🔗 https://play.google.com/store/apps/details?id={r['id']}")
        print()
    if not rockets:
        print("Ракет не найдено")
    else:
        print(f"Итого: {len(rockets)} ракет из {len(ids_list)} проверенных")
