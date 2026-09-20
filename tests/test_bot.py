import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bot
import pytz
import requests


def test_config(**overrides):
    values = {
        "telegram_token": "",
        "channel_id": "",
        "timezone_name": "Europe/Warsaw",
        "post_times": ("10:00", "19:00"),
        "max_posts_per_run": 5,
        "hours_lookback": 48,
        "data_dir": Path("data"),
        "request_timeout": 15.0,
        "post_delay_seconds": 0.0,
        "log_level": "INFO",
        "dry_run": True,
        "llm_api_key": "",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "",
    }
    values.update(overrides)
    return bot.Config(**values)


class ConfigurationTests(unittest.TestCase):
    def test_post_times_are_normalized_and_sorted(self):
        self.assertEqual(bot.parse_post_times("19:00, 9:05,19:00"), ("09:05", "19:00"))

    def test_invalid_post_time_is_rejected(self):
        with self.assertRaises(bot.ConfigurationError):
            bot.parse_post_times("25:00")

    def test_zero_request_timeout_is_rejected(self):
        with (
            mock.patch.dict("os.environ", {"REQUEST_TIMEOUT": "0"}),
            self.assertRaises(bot.ConfigurationError),
        ):
            bot.Config.from_env(dry_run=True)

    def test_live_delivery_requires_telegram_credentials(self):
        with self.assertRaises(bot.ConfigurationError):
            test_config(dry_run=False).validate_delivery()


class ContentTests(unittest.TestCase):
    def test_tracking_parameters_and_fragments_are_removed(self):
        value = "HTTPS://Example.COM/news?a=1&utm_source=x&fbclid=y#comments"
        self.assertEqual(bot.normalize_url(value), "https://example.com/news?a=1")

    def test_caption_escapes_untrusted_feed_content(self):
        entry = SimpleNamespace(
            title="Games &amp; &lt;Things&gt;",
            summary="A <b>bold</b> update &amp; surprise.",
            link="https://example.com/post?utm_source=rss",
        )
        caption = bot.build_caption(entry, test_config(), bot.build_http_session())
        self.assertIn("Games &amp; &lt;Things&gt;", caption)
        self.assertIn("update &amp; surprise", caption)
        self.assertIn('href="https://example.com/post"', caption)

    def test_local_formatting_is_deterministic(self):
        first = bot.fallback_body("Title", "Summary.")
        second = bot.fallback_body("Title", "Summary.")
        self.assertEqual(first, second)

    def test_freshness_uses_utc(self):
        entry = SimpleNamespace(
            published_parsed=time.strptime("2026-09-20 10:00:00", "%Y-%m-%d %H:%M:%S")
        )
        now = datetime(2026, 9, 20, 11, 30, tzinfo=timezone.utc)
        self.assertTrue(bot.within_hours(entry, 2, now=now))
        self.assertFalse(bot.within_hours(entry, 1, now=now))

    def test_llm_rewrite_uses_openai_compatible_endpoint(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": "Короткая новость & факт."}}]
                }

        class Session:
            def __init__(self):
                self.request = None

            def post(self, url, **kwargs):
                self.request = (url, kwargs)
                return Response()

        session = Session()
        config = test_config(
            llm_api_key="secret",
            llm_base_url="https://llm.example/v1",
            llm_model="example-model",
        )
        result = bot.llm_body("Title", "Summary", config, session)
        self.assertEqual(result, "Короткая новость & факт.")
        self.assertEqual(session.request[0], "https://llm.example/v1/chat/completions")
        self.assertEqual(session.request[1]["json"]["model"], "example-model")

    def test_llm_failure_uses_local_fallback(self):
        class Session:
            def post(self, *args, **kwargs):
                raise requests.Timeout("unavailable")

        config = test_config(llm_api_key="secret", llm_model="example-model")
        self.assertIsNone(bot.llm_body("Title", "Summary", config, Session()))


class StateTests(unittest.TestCase):
    def test_state_is_saved_and_loaded_with_normalized_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "posted.json"
            store = bot.PostedStore(path)
            store.add("https://example.com/item?utm_campaign=test#part")
            store.save()

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["urls"], ["https://example.com/item"])

            loaded = bot.PostedStore(path)
            loaded.load()
            self.assertTrue(loaded.contains("https://example.com/item?utm_source=rss"))

    def test_invalid_state_does_not_crash_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "posted.json"
            path.write_text("not-json", encoding="utf-8")
            store = bot.PostedStore(path)
            store.load()
            self.assertEqual(store.urls, [])


class SchedulerTests(unittest.TestCase):
    def test_next_run_uses_same_day_when_possible(self):
        tz = pytz.timezone("Europe/Warsaw")
        now = tz.localize(datetime(2026, 9, 20, 12, 0))  # noqa: DTZ001
        result = bot.next_run_at(now, ("10:00", "19:00"))
        self.assertEqual(result.hour, 19)
        self.assertEqual(result.date(), now.date())

    def test_next_run_rolls_to_next_day(self):
        tz = pytz.timezone("Europe/Warsaw")
        now = tz.localize(datetime(2026, 9, 20, 20, 0))  # noqa: DTZ001
        result = bot.next_run_at(now, ("10:00", "19:00"))
        self.assertEqual(result.hour, 10)
        self.assertEqual(result.date().isoformat(), "2026-09-21")


class FakeTelegramBot:
    def __init__(self):
        self.messages = []

    def send_photo(self, *args, **kwargs):
        raise RuntimeError("image rejected")

    def send_message(self, channel_id, caption, parse_mode):
        self.messages.append((channel_id, caption, parse_mode))


class PublisherTests(unittest.TestCase):
    def test_failed_photo_falls_back_to_text(self):
        config = test_config(
            dry_run=False,
            telegram_token="123:token",
            channel_id="@channel",
        )
        publisher = bot.Publisher.__new__(bot.Publisher)
        publisher.config = config
        publisher.bot = FakeTelegramBot()
        publisher.send("caption", "https://example.com/image.jpg")
        self.assertEqual(publisher.bot.messages, [("@channel", "caption", "HTML")])


if __name__ == "__main__":
    unittest.main()
