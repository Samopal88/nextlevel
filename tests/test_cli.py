import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bot
import cli


class ConfigurationPathTests(unittest.TestCase):
    def test_explicit_config_directory_wins(self):
        with mock.patch.dict(
            os.environ,
            {"NEXTLEVEL_CONFIG_DIR": "/tmp/custom-nextlevel"},
            clear=False,
        ):
            self.assertEqual(
                bot.user_config_dir(), Path("/tmp/custom-nextlevel")
            )

    def test_config_is_written_without_exposing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            with mock.patch.object(cli, "_data_dir", return_value=Path(directory) / "data"):
                cli.write_config(
                    path,
                    token="123456:secret-token",
                    channel_id="@example",
                    timezone_name="Asia/Kamchatka",
                    post_times="10:00,19:00",
                )
            content = path.read_text(encoding="utf-8")
            self.assertIn('TELEGRAM_CHANNEL_ID="@example"', content)
            self.assertIn('TIMEZONE="Asia/Kamchatka"', content)
            self.assertNotIn("YOUR_TELEGRAM_BOT_TOKEN", content)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class TelegramVerificationTests(unittest.TestCase):
    def test_admin_bot_is_accepted(self):
        client = mock.Mock()
        client.get_me.return_value = SimpleNamespace(id=42, username="example_bot")
        client.get_chat.return_value = SimpleNamespace(title="Example Channel")
        client.get_chat_member.return_value = SimpleNamespace(status="administrator")
        with mock.patch.object(cli.telebot, "TeleBot", return_value=client):
            ok, message = cli.verify_telegram("123:secret", "@example")
        self.assertTrue(ok)
        self.assertIn("@example_bot", message)

    def test_error_message_redacts_token(self):
        token = "123:very-secret"
        with mock.patch.object(
            cli.telebot,
            "TeleBot",
            side_effect=RuntimeError(f"request failed for {token}"),
        ):
            ok, message = cli.verify_telegram(token, "@example")
        self.assertFalse(ok)
        self.assertNotIn(token, message)
        self.assertIn("<redacted>", message)


class CommandTests(unittest.TestCase):
    def test_preview_maps_to_safe_dry_run(self):
        with mock.patch.object(bot, "main", return_value=0) as bot_main:
            result = cli.main(["preview"])
        self.assertEqual(result, 0)
        bot_main.assert_called_once_with(["--dry-run"])

    def test_systemd_environment_quotes_paths(self):
        self.assertEqual(
            cli._systemd_environment("NEXTLEVEL_ENV_FILE", "/home/user/My App/.env"),
            'Environment="NEXTLEVEL_ENV_FILE=/home/user/My App/.env"',
        )

    def test_windows_autostart_creates_and_starts_task(self):
        completed = SimpleNamespace(returncode=0)
        config_path = SimpleNamespace(resolve=lambda: "config.env")
        with (
            mock.patch.object(cli.os, "name", "nt"),
            mock.patch.object(cli.subprocess, "run", return_value=completed) as run,
            mock.patch.object(
                cli.bot, "default_env_file", return_value=config_path
            ),
        ):
            self.assertTrue(cli.install_autostart())
        self.assertEqual(run.call_count, 2)
        self.assertIn("/Create", run.call_args_list[0].args[0])
        self.assertIn("/Run", run.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
