#!/usr/bin/env python3
"""
TikTok Trending/Explore через браузер OpenClaw (CDP порт 18800).
Открывает tiktok.com/explore и перехватывает API ответы.
Не требует msToken или авторизации - работает автономно.

Результат: /tmp/tiktok_trending.json
Stdout: {"count": N, "source": "tiktok_trending"}
"""
import asyncio, json, sys, os
from datetime import datetime, timezone

OUT_FILE = '/tmp/tiktok_trending.json'
CDP_URL = 'http://127.0.0.1:18800'

MIN_VIEWS = 500_000   # для Trending берём только реально вирусные
MAX_AGE_DAYS = 14     # свежие (не старше 2 недель)
MAX_SCROLL = 5        # сколько раз скроллить для загрузки
SCROLL_PAUSE = 2.5    # пауза между скроллами


def fmt_views(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(v)

def grade(vpd):
    if vpd >= 5_000_000: return "🔥🔥🔥"
    if vpd >= 1_000_000: return "🔥🔥"
    if vpd >= 300_000:   return "🔥"
    if vpd >= 100_000:   return "🚀🔥"
    if vpd >= 30_000:    return "🚀"
    return "⚡"

def parse_item(item):
    try:
        vid_id = str(item.get('id','') or item.get('aweme_id',''))
        if not vid_id: return None

        desc = item.get('desc', '') or ''
        create_time = item.get('createTime', 0) or item.get('create_time', 0) or 0

        author = item.get('author', {}) or {}
        if not isinstance(author, dict): author = {}
        username = author.get('uniqueId','') or author.get('unique_id','') or ''
        subs = author.get('followerCount', 0) or author.get('follower_count', 0) or 0

        stats = item.get('stats', {}) or item.get('statistics', {}) or {}
        if not isinstance(stats, dict): stats = {}
        views = stats.get('playCount', 0) or stats.get('play_count', 0) or 0
        likes = stats.get('diggCount', 0) or stats.get('digg_count', 0) or 0

        if views < MIN_VIEWS: return None

        age_days = 7  # дефолт
        if create_time:
            try:
                dt = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
                age_days = max(1, (datetime.now(tz=timezone.utc) - dt).days)
            except: pass

        if age_days > MAX_AGE_DAYS: return None

        vpd = views // max(age_days, 1)
        ratio = round(views / max(subs, 1), 1)

        video_data = item.get('video', {}) or {}
        thumb = (video_data.get('cover','') or
                 video_data.get('dynamicCover','') or
                 video_data.get('originCover','') or '')

        return {
            'id': vid_id,
            'title': desc[:200],
            'channel': f'@{username}' if username else '',
            'channel_id': str(author.get('id','') or ''),
            'views': views,
            'views_str': fmt_views(views),
            'vpd': vpd,
            'vpd_str': fmt_views(vpd),
            'likes': likes,
            'subs': subs,
            'subs_str': fmt_views(subs),
            'age_days': age_days,
            'ratio': ratio,
            'grade': grade(vpd),
            'url': f'https://www.tiktok.com/@{username}/video/{vid_id}',
            'thumb': thumb,
            'source': 'tiktok_trending',
            'kind': 'Short',
            'platform': 'tiktok',
        }
    except Exception as e:
        return None


async def main():
    from playwright.async_api import async_playwright

    print("Открываю TikTok Explore через браузер...", file=sys.stderr)
    captured_items = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            if not ctx:
                print("Нет контекстов браузера", file=sys.stderr)
                return []

            page = await ctx.new_page()

            async def handle_response(response):
                url = response.url
                if 'api/explore/item_list' in url and response.status == 200:
                    try:
                        body = await response.json()
                        items = (body.get('itemList', []) or
                                 body.get('item_list', []) or
                                 body.get('aweme_list', []))
                        if items:
                            captured_items.extend(items)
                            print(f"  Поймали {len(items)} видео ({len(captured_items)} всего)", file=sys.stderr)
                    except:
                        pass

            page.on('response', handle_response)

            await page.goto('https://www.tiktok.com/explore',
                           wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)

            # Скроллим для загрузки большего контента
            for i in range(MAX_SCROLL):
                await page.evaluate(f'window.scrollTo(0, {800 + i * 600})')
                await asyncio.sleep(SCROLL_PAUSE)

            await page.close()
            await browser.close()

    except Exception as e:
        print(f"Браузер недоступен: {e}", file=sys.stderr)
        # Сохраняем пустой файл - не ломаем пайплайн
        with open(OUT_FILE, 'w') as f:
            json.dump([], f)
        print(json.dumps({'count': 0, 'source': 'tiktok_trending', 'error': 'browser unavailable'}))
        return

    # Парсим и фильтруем
    videos = []
    seen = set()
    for item in captured_items:
        v = parse_item(item)
        if v and v['id'] not in seen:
            seen.add(v['id'])
            videos.append(v)

    # Сортируем по vpd
    videos.sort(key=lambda x: x['vpd'], reverse=True)
    top = videos[:30]

    with open(OUT_FILE, 'w') as f:
        json.dump(top, f, ensure_ascii=False, indent=2)

    print(f"\nTrending: {len(top)} видео из {len(captured_items)} проверенных", file=sys.stderr)
    for v in top[:10]:
        print(f"  {v['grade']} {v['channel']:20} | {v['vpd_str']:>7}/д | {v['title'][:40]}", file=sys.stderr)

    print(json.dumps({'count': len(top), 'source': 'tiktok_trending'}))


if __name__ == '__main__':
    asyncio.run(main())
