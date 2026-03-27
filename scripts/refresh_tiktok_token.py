#!/usr/bin/env python3
"""
Обновляет msToken TikTok из браузера через Playwright CDP.
Запускать перед fetch_tiktok_playwright.py.
"""
import asyncio, json, sys

TOKEN_FILE = '/Users/andrey/.openclaw/workspace/.tiktok_ms_token'

async def main():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as pw:
        try:
            # Подключаемся к уже запущенному браузеру OpenClaw
            browser = await pw.chromium.connect_over_cdp('http://127.0.0.1:18800')
            contexts = browser.contexts
            
            # Ищем контекст с TikTok или берём первый
            ctx = contexts[0] if contexts else None
            if not ctx:
                print("Нет контекстов браузера", file=sys.stderr)
                return False
            
            # Ищем страницу TikTok
            pages = ctx.pages
            tiktok_page = next((p for p in pages if 'tiktok.com' in p.url), None)
            
            if not tiktok_page:
                # Открываем TikTok на первой странице
                tiktok_page = pages[0] if pages else await ctx.new_page()
                await tiktok_page.goto('https://www.tiktok.com', wait_until='domcontentloaded', timeout=15000)
                await asyncio.sleep(3)
            
            # Получаем cookie
            cookies = await ctx.cookies(['https://www.tiktok.com'])
            ms_token = next((c['value'] for c in cookies if c['name'] == 'msToken'), None)
            
            await browser.close()
            
            if ms_token and len(ms_token) > 50:
                with open(TOKEN_FILE, 'w') as f:
                    f.write(ms_token)
                print(f"msToken обновлён ({len(ms_token)} chars)")
                return True
            else:
                print("msToken не найден в браузере", file=sys.stderr)
                return False
                
        except Exception as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return False

if __name__ == '__main__':
    ok = asyncio.run(main())
    sys.exit(0)  # всегда 0 - не ломаем пайплайн если браузер закрыт
