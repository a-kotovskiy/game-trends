#!/usr/bin/env python3
"""Генерирует идеи для игр на основе трендов из data.json"""
import json, sys, os

DATA_FILE = "/Users/andrey/.openclaw/workspace/dashboard/data.json"

try:
    with open(DATA_FILE) as f:
        data = json.load(f)
except:
    print(json.dumps([]))
    sys.exit()

rockets = data.get("rockets", [])
videos = data.get("videos", [])

# Анализируем жанры ракет
genre_counts = {}
for r in rockets:
    genre = r.get("genre", "").split("·")[0].strip()
    if genre:
        genre_counts[genre] = genre_counts.get(genre, 0) + 1

top_genre = max(genre_counts, key=genre_counts.get) if genre_counts else "Action"

# Топ видео для вдохновения
top_video = videos[0]["title"] if videos else "viral mobile game"

# Статичная база идей, адаптированная под текущие тренды
IDEAS_BASE = [
    {
        "emoji": "🎯",
        "title": f"Клон-улучшение топового жанра: {top_genre}",
        "desc": f"Возьми механику из жанра {top_genre}, добавь одну уникальную фишку. Бюджет: 2-4 недели.",
        "tags": ["Indie", "Быстрый старт"],
        "difficulty": "Средняя",
    },
    {
        "emoji": "🔄",
        "title": "Гибридная казуалка: два жанра в одном",
        "desc": "Смешай пазл + idle или match-3 + roguelike. Виральность за счёт новизны механики.",
        "tags": ["Casual", "Hybrid"],
        "difficulty": "Средняя",
    },
    {
        "emoji": "📱",
        "title": "Мобильная co-op игра",
        "desc": "Локальный или онлайн кооператив на 2-4 игрока. Рынок недонасыщен, особенно на мобайле.",
        "tags": ["Multiplayer", "Mobile"],
        "difficulty": "Высокая",
    },
    {
        "emoji": "⚡",
        "title": "Hypercasual с виральным хуком",
        "desc": "Одна механика + шаринг результата. Цель: первые 10K скачиваний за неделю органики.",
        "tags": ["Hypercasual", "Viral"],
        "difficulty": "Низкая",
    },
    {
        "emoji": "🌍",
        "title": "Idle/кликер с нарративом",
        "desc": "Добавь историю и персонажей в idle-механику. Retention x3 по сравнению с чистым idle.",
        "tags": ["Idle", "Narrative"],
        "difficulty": "Средняя",
    },
]

# Добавляем идею на основе топ видео
if top_video:
    IDEAS_BASE.append({
        "emoji": "🎬",
        "title": f"Игра по хайпу: вдохновение из YouTube",
        "desc": f"Тренд: «{top_video[:60]}». Сделай мобильную игру по механике из этого видео.",
        "tags": ["Trend", "YouTube"],
        "difficulty": "Средняя",
    })

print(json.dumps(IDEAS_BASE[:5], ensure_ascii=False))
