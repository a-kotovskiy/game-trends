#!/usr/bin/env python3
"""Собирает игровые новости из RSS-лент"""
import subprocess, re, json, sys
from datetime import datetime, timedelta
from html import unescape

FEEDS = [
    ("TouchArcade", "🎮", "https://toucharcade.com/feed/"),
    ("Pocket Gamer", "📱", "https://www.pocketgamer.com/rss/"),
    ("Game Developer", "🛠", "https://www.gamedeveloper.com/rss.xml"),
    ("IGN", "🔥", "https://feeds.feedburner.com/ign/games-all"),
    ("Eurogamer", "🎲", "https://www.eurogamer.net/?format=rss"),
]

HEADERS = '-H "User-Agent: Mozilla/5.0" -H "Accept: application/rss+xml,application/xml;q=0.9,*/*;q=0.8"'
CUTOFF = datetime.now() - timedelta(days=7)

def fetch_feed(url):
    try:
        cmd = f'curl -sL --max-time 10 "{url}" {HEADERS}'
        return subprocess.check_output(cmd, shell=True, timeout=12).decode('utf-8', errors='ignore')
    except:
        return ""

def parse_date(s):
    if not s: return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s.strip()[:30], fmt[:len(s.strip()[:30])])
        except:
            pass
    return None

def clean(s):
    s = unescape(s or "")
    # Убираем CDATA обёртку
    s = re.sub(r'<!\[CDATA\[|\]\]>', '', s)
    # Убираем HTML теги
    s = re.sub(r'<[^>]+>', '', s)
    # Убираем хвосты RSS мусора
    s = re.sub(r'\s*(MORE|READ MORE|CONTINUE|\.\.\.)\]?\]?>?\s*$', '...', s, flags=re.IGNORECASE)
    return s.strip()

GAME_KEYWORDS = [
    'game','gaming','mobile','android','ios','launch','release','update',
    'trailer','gameplay','studio','developer','publisher','rpg','indie',
    'multiplayer','esport','steam','nintendo','playstation','xbox'
]

news = []
seen_titles = set()

for source, emoji, url in FEEDS:
    xml = fetch_feed(url)
    if not xml:
        continue

    items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
    for item in items[:20]:
        def g(pattern, text):
            m = re.search(pattern, text, re.DOTALL)
            return m.group(1) if m else ""
        title = clean(g(r'<title>(.*?)</title>', item))
        link = clean(g(r'<link>(.*?)</link>', item) or g(r'<guid>(.*?)</guid>', item))
        desc = clean(g(r'<description>(.*?)</description>', item))[:180]
        pub_date = clean(g(r'<pubDate>(.*?)</pubDate>', item))

        if not title or title in seen_titles:
            continue

        # Фильтр: только игровые новости
        title_lower = title.lower()
        if not any(kw in title_lower for kw in GAME_KEYWORDS):
            continue

        seen_titles.add(title)
        news.append({
            "emoji": emoji,
            "source": source,
            "title": title[:100],
            "desc": desc[:180],
            "url": link,
            "date": pub_date,
        })

    if len(news) >= 20:
        break

# Ограничиваем до 8 свежих
news = news[:8]

print(json.dumps(news, ensure_ascii=False))
