#!/usr/bin/env python3
"""
TikTok хайп-видео через TikTokApi 7.x (официальная неофициальная либа).
Требует ms_token в /Users/andrey/.openclaw/workspace/.tiktok_ms_token
(получить из браузера: tiktok.com → DevTools → Cookies → msToken)

Результат: /tmp/tiktok_playwright.json
Stdout: {"count": N, "source": "tiktok_playwright"}
"""
import asyncio
import json
import sys
import os
from datetime import datetime, timezone

OUT_FILE = '/tmp/tiktok_playwright.json'
MS_TOKEN_FILE = os.path.expanduser('/Users/andrey/.openclaw/workspace/.tiktok_ms_token')

HASHTAGS = ['mobilegame', 'newgame', 'viralGame', 'addictivegame', 'mobilegaming']
MIN_VIEWS = 50_000
MAX_AGE_DAYS = 30
MIN_RATIO = 5.0
MAX_PER_HASHTAG = 30


def fmt_views(v):
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(v)


def grade_video(vpd):
    if vpd >= 500_000: return "🔥🔥"
    if vpd >= 100_000: return "🔥"
    if vpd >= 50_000:  return "🚀🔥"
    if vpd >= 20_000:  return "🚀"
    return "⚡"


def parse_video(video_obj):
    """Превращает объект TikTokApi в наш формат."""
    try:
        vid = video_obj
        # Поддержка как dict так и объекта
        if hasattr(vid, 'as_dict'):
            d = vid.as_dict
        elif isinstance(vid, dict):
            d = vid
        else:
            d = vars(vid) if hasattr(vid, '__dict__') else {}

        vid_id = str(d.get('id', '') or '')
        if not vid_id:
            return None

        desc = d.get('desc', '') or ''
        create_time = d.get('createTime', 0) or d.get('create_time', 0) or 0

        # Автор
        author = d.get('author', {}) or {}
        if not isinstance(author, dict):
            author = {}
        username = author.get('uniqueId', '') or author.get('unique_id', '') or ''
        author_id = str(author.get('id', '') or '')
        subs = author.get('followerCount', 0) or author.get('follower_count', 0) or 0

        # Статистика
        stats = d.get('stats', {}) or d.get('statistics', {}) or {}
        if not isinstance(stats, dict):
            stats = {}
        views = stats.get('playCount', 0) or stats.get('play_count', 0) or 0
        likes = stats.get('diggCount', 0) or stats.get('digg_count', 0) or 0

        if views < MIN_VIEWS:
            return None

        # Возраст
        age_days = 15  # дефолт
        if create_time:
            try:
                dt = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
                age_days = max(1, (datetime.now(tz=timezone.utc) - dt).days)
            except Exception:
                pass

        if age_days > MAX_AGE_DAYS:
            return None

        vpd = views // max(age_days, 1)
        ratio = views / max(subs, 1)

        if ratio < MIN_RATIO:
            return None

        # Thumbnail
        video_data = d.get('video', {}) or {}
        thumb = (video_data.get('cover', '') or
                 video_data.get('dynamicCover', '') or
                 video_data.get('originCover', '') or '')

        return {
            'id': vid_id,
            'title': desc[:200],
            'channel': f'@{username}' if username else f'user_{author_id}',
            'channel_id': author_id,
            'views': views,
            'views_str': fmt_views(views),
            'vpd': vpd,
            'vpd_str': fmt_views(vpd),
            'likes': likes,
            'subs': subs,
            'subs_str': fmt_views(subs),
            'age_days': age_days,
            'ratio': round(ratio, 1),
            'grade': grade_video(vpd),
            'url': f'https://www.tiktok.com/@{username}/video/{vid_id}',
            'thumb': thumb,
            'source': 'tiktok_playwright',
            'kind': 'Short',
            'platform': 'tiktok',
        }
    except Exception as e:
        print(f"  parse_video error: {e}", file=sys.stderr)
        return None


async def main():
    # Проверяем ms_token
    ms_token = None
    if os.path.exists(MS_TOKEN_FILE):
        with open(MS_TOKEN_FILE) as f:
            ms_token = f.read().strip()
    
    if not ms_token:
        print("⚠️  ms_token не найден!", file=sys.stderr)
        print(f"Положи msToken из браузера в: {MS_TOKEN_FILE}", file=sys.stderr)
        print("Как получить: открой tiktok.com → F12 → Application → Cookies → msToken", file=sys.stderr)
        # Пробуем без токена (может не работать)
        ms_token = None
    else:
        print(f"ms_token найден ({len(ms_token)} chars)", file=sys.stderr)

    from TikTokApi import TikTokApi

    all_videos = []

    try:
        async with TikTokApi() as api:
            print("Создаю сессию TikTokApi...", file=sys.stderr)
            await api.create_sessions(
                num_sessions=1,
                headless=True,
                ms_tokens=[ms_token] if ms_token else None,
                sleep_after=3,
                suppress_resource_load_types=["image", "media", "font", "stylesheet"],
            )
            print("Сессия создана!", file=sys.stderr)

            for hashtag in HASHTAGS:
                print(f"Собираю #{hashtag}...", file=sys.stderr)
                try:
                    tag = api.hashtag(name=hashtag)
                    count = 0
                    async for video in tag.videos(count=MAX_PER_HASHTAG):
                        v = parse_video(video)
                        if v:
                            all_videos.append(v)
                            count += 1
                    print(f"  #{hashtag}: {count} видео прошли фильтр", file=sys.stderr)
                except Exception as e:
                    print(f"  #{hashtag} ошибка: {e}", file=sys.stderr)

    except Exception as e:
        print(f"TikTokApi error: {e}", file=sys.stderr)
        # Сохраняем пустой файл
        with open(OUT_FILE, 'w') as f:
            json.dump([], f)
        print(json.dumps({'count': 0, 'source': 'tiktok_playwright', 'error': str(e)}))
        return

    # Дедупликация и сортировка
    seen = set()
    unique = []
    for v in all_videos:
        if v['id'] not in seen:
            seen.add(v['id'])
            unique.append(v)

    unique.sort(key=lambda x: x['vpd'], reverse=True)
    top30 = unique[:30]

    with open(OUT_FILE, 'w') as f:
        json.dump(top30, f, ensure_ascii=False, indent=2)

    print(f"Сохранено {len(top30)} TikTok видео", file=sys.stderr)
    print(json.dumps({'count': len(top30), 'source': 'tiktok_playwright'}))


if __name__ == '__main__':
    asyncio.run(main())
