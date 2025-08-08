#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Next Level Telegram bot
- Parses gaming + anime news from RSS
- Rewrites into short 3–5 sentence posts in a witty style
- Pulls an image from the article (media tags or OpenGraph)
- Posts to a Telegram channel at scheduled times
"""

import os
import re
import json
import time
import html
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
import requests
import feedparser
from bs4 import BeautifulSoup

import telebot  # pyTelegramBotAPI

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()  # e.g. @nextlvlgm or -1001234567890
TIMEZONE = os.getenv("TIMEZONE", "Europe/Warsaw")
POST_TIMES = [t.strip() for t in os.getenv("POST_TIMES", "10:00,19:00").split(",") if t.strip()]  # 24h HH:MM
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "5"))
HOURS_LOOKBACK = int(os.getenv("HOURS_LOOKBACK", "48"))
DATA_DIR = os.getenv("DATA_DIR", "data")
POSTED_DB_PATH = os.path.join(DATA_DIR, "posted.json")

FEEDS_GAMING = [
    "https://www.pcgamer.com/rss/",
    "https://www.polygon.com/rss/index.xml",
    "https://www.gamespot.com/feeds/news/",
    "https://www.eurogamer.net/feed",
    "https://feeds.ign.com/ign/all"
]

FEEDS_ANIME = [
    "https://www.animenewsnetwork.com/all/rss.xml",
    "https://animecorner.me/feed/"
]

ALL_FEEDS = FEEDS_GAMING + FEEDS_ANIME

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("nextlevel-bot")

def ensure_posted_db() -> dict:
    if not os.path.exists(POSTED_DB_PATH):
        os.makedirs(os.path.dirname(POSTED_DB_PATH), exist_ok=True)
        with open(POSTED_DB_PATH, "w", encoding="utf-8") as f:
            json.dump({"urls": []}, f, ensure_ascii=False, indent=2)
    with open(POSTED_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_posted_db(db: dict):
    with open(POSTED_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def url_already_posted(url: str, db: dict) -> bool:
    return url in db.get("urls", [])

def mark_url_posted(url: str, db: dict):
    db.setdefault("urls", []).append(url)
    db["urls"] = db["urls"][-5000:]

def strip_html(text: str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)

def pick_image_from_entry(entry) -> Optional[str]:
    try:
        if "media_content" in entry and entry.media_content:
            return entry.media_content[0].get("url")
    except Exception:
        pass
    try:
        if "media_thumbnail" in entry and entry.media_thumbnail:
            return entry.media_thumbnail[0].get("url")
    except Exception:
        pass
    try:
        if "content" in entry:
            for c in entry.content:
                soup = BeautifulSoup(c.value, "html.parser")
                img = soup.find("img")
                if img and img.get("src"):
                    return img["src"]
    except Exception:
        pass
    try:
        soup = BeautifulSoup(getattr(entry, "summary", ""), "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    except Exception:
        pass
    try:
        url = entry.link
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NextLevelBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                return og["content"]
    except Exception:
        pass
    return None

def compact_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def shorten(s: str, length: int) -> str:
    if len(s) <= length:
        return s
    return s[:length-1].rstrip() + "…"

def style_next_level(title: str, summary: str) -> str:
    title_clean = compact_whitespace(strip_html(title))
    summ_clean = compact_whitespace(strip_html(summary))
    sentences = re.split(r"(?<=[.!?])\s+", summ_clean)
    base = " ".join(sentences[:2]) if sentences else summ_clean
    base = shorten(base, 450)

    openers = [
        "Коротко по делу:",
        "Если по-геймерски:",
        "С юмором и по фактам:",
        "TL;DR для своих:"
    ]
    closers = [
        "Короче, апгрейд в копилку.",
        "Ставим галочку и идём дальше.",
        "Следим, пока баги не победят нас.",
        "Звучит как новый квест."
    ]

    opener = openers[hash(title_clean) % len(openers)]
    closer = closers[hash(summ_clean) % len(closers)]
    hook = shorten(title_clean, 140)
    mood = [
        "Без воды, только хардкор.",
        "Ирония включена, токсичности — ноль.",
        "Готовим попкорн и проверяем патчноуты.",
        "Мемы уже подлетают в комменты."
    ][hash(title_clean + summ_clean) % 4]

    parts = [
        f"<b>{html.escape(hook)}</b>",
        f"{opener} {base}",
        mood,
        closer
    ]
    return " ".join(parts)

def html_link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'

def build_caption(entry) -> str:
    title = getattr(entry, "title", "(без названия)")
    link = getattr(entry, "link", "")
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    styled = style_next_level(title, summary)
    return f"{styled}\n\n{html_link(link, 'Источник')}"

def within_hours(published_parsed, hours: int) -> bool:
    if not published_parsed:
        return True
    from datetime import timezone as _tz
    ts = datetime.fromtimestamp(time.mktime(published_parsed), tz=_tz.utc)
    now = datetime.now(tz=_tz.utc)
    return (now - ts) <= timedelta(hours=hours)

def fetch_fresh_entries(feeds: List[str], hours: int):
    entries = []
    for url in feeds:
        try:
            fp = feedparser.parse(url)
            for e in fp.entries:
                if within_hours(getattr(e, "published_parsed", None), hours):
                    entries.append(e)
        except Exception as ex:
            logger.warning("Feed parse failed: %s (%s)", url, ex)
    def key(e):
        ts = getattr(e, "published_parsed", None)
        return time.mktime(ts) if ts else 0
    entries.sort(key=key, reverse=True)
    return entries

def pick_new_items(entries, db: dict, limit: int):
    fresh = []
    for e in entries:
        link = getattr(e, "link", "")
        if not link or link in db.get("urls", []):
            continue
        fresh.append(e)
        if len(fresh) >= limit:
            break
    return fresh

def run_once():
    if not TOKEN or not CHANNEL_ID:
        logger.error("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID env vars.")
        return
    bot = telebot.TeleBot(TOKEN)

    db = ensure_posted_db()
    entries = fetch_fresh_entries(ALL_FEEDS, HOURS_LOOKBACK)
    to_post = pick_new_items(entries, db, MAX_POSTS_PER_RUN)

    if not to_post:
        logger.info("No new items to post.")
        return

    posted = 0
    for e in to_post:
        caption = build_caption(e)
        image_url = pick_image_from_entry(e)
        try:
            if image_url:
                bot.send_photo(CHANNEL_ID, image_url, caption=caption, parse_mode="HTML")
            else:
                bot.send_message(CHANNEL_ID, caption, parse_mode="HTML")
            db.setdefault("urls", []).append(getattr(e, "link", ""))
            save_posted_db(db)
            posted += 1
            time.sleep(2)
        except Exception as ex:
            logger.error("Send failed: %s", ex)
    logger.info("Posted %d items.", posted)

def sleep_until_next_schedule(now_local, times_local):
    from datetime import timedelta
    today = now_local.date()
    candidates = []
    for t in times_local:
        hh, mm = map(int, t.split(":"))
        dt = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dt > now_local:
            candidates.append(dt)
    if not candidates:
        hh, mm = map(int, times_local[0].split(":"))
        next_day = (now_local + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        return (next_day - now_local).total_seconds()
    return (min(candidates) - now_local).total_seconds()

def run_scheduler():
    tz = pytz.timezone(TIMEZONE)
    logging.info("Scheduler started. TZ=%s, times=%s", TIMEZONE, ",".join(POST_TIMES))
    while True:
        now_local = datetime.now(tz)
        secs = sleep_until_next_schedule(now_local, POST_TIMES)
        time.sleep(max(1, secs))
        try:
            run_once()
        except Exception as ex:
            logging.exception("run_once failed: %s", ex)
        time.sleep(5)

if __name__ == "__main__":
    if os.getenv("RUN_ONCE", "0") == "1":
        run_once()
    else:
        run_scheduler()
