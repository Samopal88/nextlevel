#!/usr/bin/env python3
"""Next Level: scheduled Telegram posts from gaming and anime RSS feeds."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import json
import logging
import os
import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as datetime_time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import pytz
import requests
import telebot
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("nextlevel")
CAPTION_BODY_LIMIT = 700
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}

FEEDS_GAMING = (
    "https://www.pcgamer.com/rss/",
    "https://www.polygon.com/rss/index.xml",
    "https://www.gamespot.com/feeds/news/",
    "https://www.eurogamer.net/feed",
    "https://feeds.ign.com/ign/all",
)

FEEDS_ANIME = (
    "https://www.animenewsnetwork.com/all/rss.xml",
    "https://animecorner.me/feed/",
)

ALL_FEEDS = FEEDS_GAMING + FEEDS_ANIME


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return parsed


def _non_negative_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default))
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must not be negative")
    return parsed


def _positive_float(name: str, default: float) -> float:
    parsed = _non_negative_float(name, default)
    if parsed == 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return parsed


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_post_times(value: str) -> tuple[str, ...]:
    times: set[str] = set()
    for raw in value.split(","):
        item = raw.strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", item)
        if not match:
            raise ConfigurationError(f"Invalid POST_TIMES value: {item!r}")
        hour, minute = (int(part) for part in match.groups())
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ConfigurationError(f"Invalid POST_TIMES value: {item!r}")
        times.add(f"{hour:02d}:{minute:02d}")
    if not times:
        raise ConfigurationError("POST_TIMES must contain at least one HH:MM value")
    return tuple(sorted(times))


@dataclass(frozen=True)
class Config:
    telegram_token: str
    channel_id: str
    timezone_name: str
    post_times: tuple[str, ...]
    max_posts_per_run: int
    hours_lookback: int
    data_dir: Path
    request_timeout: float
    post_delay_seconds: float
    log_level: str
    dry_run: bool
    llm_api_key: str
    llm_base_url: str
    llm_model: str

    @property
    def posted_db_path(self) -> Path:
        return self.data_dir / "posted.json"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> Config:
        load_dotenv()
        timezone_name = os.getenv("TIMEZONE", "Europe/Warsaw").strip()
        try:
            pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError as exc:
            raise ConfigurationError(f"Unknown TIMEZONE: {timezone_name}") from exc

        llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        llm_model = os.getenv("LLM_MODEL", "").strip()
        if bool(llm_api_key) != bool(llm_model):
            raise ConfigurationError(
                "LLM_API_KEY and LLM_MODEL must either both be set or both be empty"
            )

        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
            timezone_name=timezone_name,
            post_times=parse_post_times(os.getenv("POST_TIMES", "10:00,19:00")),
            max_posts_per_run=_positive_int("MAX_POSTS_PER_RUN", 5),
            hours_lookback=_positive_int("HOURS_LOOKBACK", 48),
            data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
            request_timeout=_positive_float("REQUEST_TIMEOUT", 15.0),
            post_delay_seconds=_non_negative_float("POST_DELAY_SECONDS", 2.0),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            dry_run=dry_run or _env_flag("DRY_RUN"),
            llm_api_key=llm_api_key,
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip(
                "/"
            ),
            llm_model=llm_model,
        )

    def validate_delivery(self) -> None:
        if self.dry_run:
            return
        missing = []
        if not self.telegram_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.channel_id:
            missing.append("TELEGRAM_CHANNEL_ID")
        if missing:
            raise ConfigurationError(
                f"Missing required variables: {', '.join(missing)}"
            )


class PostedStore:
    """Small JSON-backed deduplication store with atomic writes."""

    def __init__(self, path: Path):
        self.path = path
        self.urls: list[str] = []

    def load(self) -> None:
        if not self.path.exists():
            self.urls = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            urls = payload.get("urls", [])
            if not isinstance(urls, list) or not all(
                isinstance(url, str) for url in urls
            ):
                raise ValueError("'urls' must be a list of strings")
            self.urls = urls[-5000:]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("Ignoring invalid state file %s: %s", self.path, exc)
            self.urls = []

    def contains(self, url: str) -> bool:
        return normalize_url(url) in self.urls

    def add(self, url: str) -> None:
        normalized = normalize_url(url)
        if normalized and normalized not in self.urls:
            self.urls.append(normalized)
            self.urls = self.urls[-5000:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"urls": self.urls}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def build_http_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {"User-Agent": "NextLevelBot/2.0 (+https://github.com/Samopal88/nextlevel)"}
    )
    return session


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            urlencode(filtered_query),
            "",
        )
    )


def strip_html(value: str) -> str:
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def shorten(value: str, length: int) -> str:
    if len(value) <= length:
        return value
    clipped = value[: max(1, length - 1)].rsplit(" ", 1)[0].rstrip()
    return (clipped or value[: length - 1]).rstrip() + "…"


def _stable_choice(values: Sequence[str], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return values[int.from_bytes(digest[:4], "big") % len(values)]


def fallback_body(title: str, summary: str) -> str:
    clean_summary = compact_whitespace(strip_html(summary))
    sentences = re.split(r"(?<=[.!?])\s+", clean_summary)
    excerpt = shorten(" ".join(sentences[:2]), 480)
    opener = _stable_choice(
        ("Коротко по делу:", "Если по-геймерски:", "TL;DR для своих:"),
        title,
    )
    closer = _stable_choice(
        (
            "Звучит как новый квест.",
            "Готовим попкорн и следим за продолжением.",
            "Ставим новость в список наблюдения.",
        ),
        title + summary,
    )
    if not excerpt:
        excerpt = "В источнике пока нет краткого описания — детали доступны по ссылке."
    return f"{opener} {excerpt}\n\n{closer}"


def llm_body(
    title: str,
    summary: str,
    config: Config,
    session: requests.Session,
) -> str | None:
    if not config.llm_enabled:
        return None
    prompt = (
        "Сделай короткую новостную заметку на русском для Telegram-канала об играх "
        "и аниме. 3–5 коротких предложений, дружелюбный тон, лёгкая ирония без "
        "токсичности. Не добавляй фактов, которых нет во входном тексте. Не используй "
        "Markdown, HTML, заголовок и ссылку.\n\n"
        f"Заголовок: {compact_whitespace(strip_html(title))}\n"
        f"Описание: {compact_whitespace(strip_html(summary))}"
    )
    try:
        response = session.post(
            f"{config.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            json={
                "model": config.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты аккуратный редактор новостного Telegram-канала.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.6,
                "max_tokens": 240,
            },
            timeout=config.request_timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        cleaned = compact_whitespace(strip_html(str(content)))
        return shorten(cleaned, CAPTION_BODY_LIMIT) or None
    except (
        requests.RequestException,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as exc:
        LOGGER.warning("LLM rewrite failed; using RSS excerpt: %s", exc)
        return None


def html_link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def build_caption(entry, config: Config, session: requests.Session) -> str:
    title = compact_whitespace(strip_html(getattr(entry, "title", "(без названия)")))
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    link = normalize_url(getattr(entry, "link", ""))
    body = llm_body(title, summary, config, session) or fallback_body(title, summary)
    body = shorten(compact_whitespace(body), CAPTION_BODY_LIMIT)
    return (
        f"<b>{html.escape(shorten(title, 160))}</b>\n\n"
        f"{html.escape(body)}\n\n"
        f"{html_link(link, 'Источник')}"
    )


def _http_url(value: str | None) -> str | None:
    if not value:
        return None
    url = value.strip()
    return url if urlsplit(url).scheme in {"http", "https"} else None


def pick_image_from_entry(
    entry,
    session: requests.Session,
    timeout: float,
) -> str | None:
    for field in ("media_content", "media_thumbnail"):
        try:
            media = getattr(entry, field, None)
            if media:
                candidate = _http_url(media[0].get("url"))
                if candidate:
                    return candidate
        except (AttributeError, IndexError, TypeError):
            pass

    for markup in (
        getattr(entry, "content", None),
        [{"value": getattr(entry, "summary", "")}],
    ):
        try:
            for item in markup or []:
                value = item.get("value", "") if isinstance(item, dict) else item.value
                image = BeautifulSoup(value, "html.parser").find("img")
                candidate = _http_url(image.get("src") if image else None)
                if candidate:
                    return candidate
        except (AttributeError, TypeError):
            pass

    article_url = _http_url(getattr(entry, "link", ""))
    if not article_url:
        return None
    try:
        response = session.get(article_url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        og_image = soup.find("meta", property="og:image")
        return _http_url(og_image.get("content") if og_image else None)
    except requests.RequestException as exc:
        LOGGER.debug("Article image lookup failed for %s: %s", article_url, exc)
        return None


def _entry_timestamp(entry) -> int | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    return calendar.timegm(parsed) if parsed else None


def within_hours(entry, hours: int, *, now: datetime | None = None) -> bool:
    timestamp = _entry_timestamp(entry)
    if timestamp is None:
        return True
    current = now or datetime.now(timezone.utc)
    published = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return current - published <= timedelta(hours=hours)


def fetch_fresh_entries(
    feeds: Iterable[str],
    hours: int,
    session: requests.Session,
    timeout: float,
) -> list:
    entries = []
    for feed_url in feeds:
        try:
            response = session.get(feed_url, timeout=timeout)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo:
                LOGGER.warning(
                    "Feed has malformed content: %s (%s)",
                    feed_url,
                    parsed.bozo_exception,
                )
            fresh = [entry for entry in parsed.entries if within_hours(entry, hours)]
            entries.extend(fresh)
            LOGGER.info("Fetched %d fresh items from %s", len(fresh), feed_url)
        except requests.RequestException as exc:
            LOGGER.warning("Feed request failed: %s (%s)", feed_url, exc)
    entries.sort(key=lambda entry: _entry_timestamp(entry) or 0, reverse=True)
    return entries


def pick_new_items(entries: Iterable, store: PostedStore, limit: int) -> list:
    selected = []
    seen_this_run: set[str] = set()
    for entry in entries:
        link = normalize_url(getattr(entry, "link", ""))
        if not link or link in seen_this_run or store.contains(link):
            continue
        selected.append(entry)
        seen_this_run.add(link)
        if len(selected) >= limit:
            break
    return selected


class Publisher:
    def __init__(self, config: Config):
        self.config = config
        self.bot = None if config.dry_run else telebot.TeleBot(config.telegram_token)

    def send(self, caption: str, image_url: str | None) -> None:
        if self.config.dry_run:
            print("\n--- Next Level preview ---")
            plain = re.sub(
                r'<a href="([^"]+)">([^<]+)</a>',
                lambda match: f"{match.group(2)}: {match.group(1)}",
                caption,
            )
            print(html.unescape(re.sub(r"</?b>", "", plain)))
            print(f"Image: {image_url or '(none)'}")
            return

        if image_url:
            try:
                self.bot.send_photo(
                    self.config.channel_id,
                    image_url,
                    caption=caption,
                    parse_mode="HTML",
                )
                return
            except Exception as exc:  # noqa: BLE001 - Telegram client errors vary by transport.
                LOGGER.warning("Photo delivery failed; retrying as text: %s", exc)
        self.bot.send_message(self.config.channel_id, caption, parse_mode="HTML")


def run_once(config: Config, *, feeds: Sequence[str] = ALL_FEEDS) -> int:
    config.validate_delivery()
    session = build_http_session()
    store = PostedStore(config.posted_db_path)
    store.load()
    entries = fetch_fresh_entries(
        feeds,
        config.hours_lookback,
        session,
        config.request_timeout,
    )
    selected = pick_new_items(entries, store, config.max_posts_per_run)
    if not selected:
        LOGGER.info("No new items to post")
        return 0

    publisher = Publisher(config)
    posted = 0
    for entry in selected:
        link = normalize_url(getattr(entry, "link", ""))
        try:
            caption = build_caption(entry, config, session)
            image_url = pick_image_from_entry(entry, session, config.request_timeout)
            publisher.send(caption, image_url)
            if not config.dry_run:
                store.add(link)
                store.save()
            posted += 1
            if config.post_delay_seconds and not config.dry_run:
                time.sleep(config.post_delay_seconds)
        except Exception:
            LOGGER.exception("Failed to publish %s", link)
    LOGGER.info("Published %d of %d selected items", posted, len(selected))
    return posted


def _localize_safely(tz, day: date, value: str) -> datetime:
    hour, minute = (int(part) for part in value.split(":"))
    naive = datetime.combine(day, datetime_time(hour=hour, minute=minute))
    try:
        return tz.localize(naive, is_dst=None)
    except pytz.NonExistentTimeError:
        return tz.localize(naive + timedelta(hours=1), is_dst=True)
    except pytz.AmbiguousTimeError:
        return tz.localize(naive, is_dst=False)


def next_run_at(now_local: datetime, post_times: Sequence[str]) -> datetime:
    tz = now_local.tzinfo
    if not hasattr(tz, "localize"):
        raise ValueError("now_local must use a pytz timezone")
    for day_offset in (0, 1):
        day = now_local.date() + timedelta(days=day_offset)
        candidates = [_localize_safely(tz, day, item) for item in post_times]
        future = [candidate for candidate in candidates if candidate > now_local]
        if future:
            return min(future)
    raise RuntimeError("Could not calculate the next scheduled run")


def run_scheduler(config: Config) -> None:
    config.validate_delivery()
    tz = pytz.timezone(config.timezone_name)
    LOGGER.info(
        "Scheduler started: timezone=%s times=%s",
        config.timezone_name,
        ",".join(config.post_times),
    )
    while True:
        now_local = datetime.now(tz)
        next_run = next_run_at(now_local, config.post_times)
        delay = max(1.0, (next_run - now_local).total_seconds())
        LOGGER.info("Next run at %s", next_run.isoformat())
        time.sleep(delay)
        try:
            run_once(config)
        except Exception:
            LOGGER.exception("Scheduled run failed")
        time.sleep(1)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="publish one batch and exit")
    mode.add_argument(
        "--dry-run", action="store_true", help="print one batch without Telegram"
    )
    mode.add_argument(
        "--check", action="store_true", help="validate configuration and exit"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = Config.from_env(dry_run=args.dry_run)
        logging.basicConfig(
            level=getattr(logging, config.log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        if args.check:
            config.validate_delivery()
            LOGGER.info("Configuration is valid")
            return 0
        if args.dry_run or args.once or _env_flag("RUN_ONCE"):
            run_once(config)
        else:
            run_scheduler(config)
        return 0
    except ConfigurationError as exc:
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s: %(message)s")
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
