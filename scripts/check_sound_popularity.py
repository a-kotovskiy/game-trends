#!/usr/bin/env python3
"""
Проверяет популярность звука TikTok через навигацию в CDP браузере.
Читает "X видео / X videos" прямо из DOM страницы /music/{id}.
"""
import asyncio, json, sys, time, re

CDP_URL = "http://127.0.0.1:18800"

def parse_count(text):
    """'34.3K видео' → 34300, '1.2M videos' → 1200000"""
    t = text.lower().replace(',', '.').strip()
    m = re.search(r'([\d.]+)\s*([km]?)', t)
    if not m: return 0
    num = float(m.group(1))
    suffix = m.group(2)
    if suffix == 'k': return int(num * 1000)
    if suffix == 'm': return int(num * 1_000_000)
    return int(num)

async def get_sound_usage(music_id: str, tab_id: str = None) -> dict:
    import aiohttp, websockets

    if not music_id:
        return {"music_id": "", "video_count": 0}

    async with aiohttp.ClientSession() as s:
        async with s.get(f'{CDP_URL}/json/list') as r:
            targets = await r.json()

    tab = next(
        (t for t in targets if t.get('targetId') == tab_id) if tab_id else
        (t for t in targets if 'tiktok.com' in t.get('url','') and t.get('type')=='page'),
        next((t for t in targets if t.get('type')=='page'), None)
    )
    if not tab:
        return {"music_id": music_id, "video_count": 0, "error": "no_tab"}

    ws_url = tab['webSocketDebuggerUrl']

    async with websockets.connect(ws_url, max_size=20_000_000) as ws:
        async def cdp(method, params=None):
            mid = int(time.time()*1000) % 999999
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if r.get('id') == mid:
                    return r.get('result', {})

        # Навигируем на страницу звука
        await cdp('Page.enable')
        await cdp('Page.navigate', {'url': f'https://www.tiktok.com/music/x-{music_id}'})
        await asyncio.sleep(3)

        # Читаем текст с количеством видео
        result = await cdp('Runtime.evaluate', {
            'expression': '''(function() {
                var texts = [];
                document.querySelectorAll("strong, [class*='count'], h2, span").forEach(function(el) {
                    var t = el.textContent.trim();
                    if (t && (t.includes('видео') || t.includes('video') || t.includes('Videos'))) {
                        texts.push(t);
                    }
                });
                // Также title страницы
                var title = document.title || '';
                var h = document.querySelector("h1,h2") ? document.querySelector("h1,h2").textContent : '';
                return JSON.stringify({texts: texts.slice(0,5), title: title, h: h});
            })()''',
            'returnByValue': True
        })

    val = result.get('result', {}).get('value', '{}')
    try:
        data = json.loads(val)
    except:
        return {"music_id": music_id, "video_count": 0, "error": "parse_fail"}

    video_count = 0
    for text in data.get('texts', []):
        c = parse_count(text)
        if c > video_count:
            video_count = c

    # Название из заголовка страницы
    title = data.get('h', '') or data.get('title', '').split('|')[0].strip()

    return {
        "music_id": music_id,
        "video_count": video_count,
        "title": title[:80],
    }


async def batch_check(music_ids: list, tab_id: str = None) -> dict:
    """Проверяет несколько звуков, возвращает {music_id: {video_count, title}}"""
    results = {}
    for mid in music_ids:
        try:
            r = await get_sound_usage(mid, tab_id)
            results[mid] = r
            await asyncio.sleep(1)  # пауза между запросами
        except Exception as e:
            results[mid] = {"music_id": mid, "video_count": 0, "error": str(e)}
    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: check_sound_popularity.py <music_id>", file=sys.stderr)
        sys.exit(1)

    try:
        import websockets, aiohttp
    except ImportError:
        import subprocess
        subprocess.run(['pip3', 'install', 'websockets', 'aiohttp', '--break-system-packages', '-q'])
        import websockets, aiohttp

    music_id = sys.argv[1]
    result = asyncio.run(get_sound_usage(music_id))
    print(json.dumps(result, ensure_ascii=False, indent=2))
