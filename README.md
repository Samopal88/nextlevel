# Next Level

[![CI](https://github.com/Samopal88/nextlevel/actions/workflows/ci.yml/badge.svg)](https://github.com/Samopal88/nextlevel/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telegram channel](https://img.shields.io/badge/Telegram-%40nextlvlgm-26A5E4?logo=telegram&logoColor=white)](https://t.me/nextlvlgm)

**Next Level** is a small, self-hosted Telegram autopublisher for gaming and anime news. It collects recent RSS entries, removes duplicates, builds compact posts, attaches article images when available, and publishes on a timezone-aware schedule.

[Русская версия](README.ru.md) · [Live channel](https://t.me/nextlvlgm)

## Why this project

Most RSS-to-Telegram scripts either repost raw feed text or require a large automation platform. Next Level stays deliberately compact: one Python service, a JSON state file, Docker support, and an optional OpenAI-compatible rewriting step.

## Features

- Seven built-in gaming and anime feeds.
- Timezone-aware scheduling with multiple daily publishing times.
- Age filtering and URL-based deduplication.
- Image discovery through RSS media, embedded content, and Open Graph metadata.
- Automatic text-only fallback when Telegram rejects a remote image.
- Optional Russian-language rewriting through any OpenAI-compatible `/chat/completions` endpoint.
- Safe `--dry-run` preview that does not require Telegram credentials.
- Atomic state writes, HTTP retries, configuration validation, Docker and Railway support.

## How it works

```text
RSS feeds -> freshness filter -> deduplication -> optional LLM rewrite
          -> image discovery -> Telegram -> posted.json
```

Without an LLM, the bot uses a deterministic local formatter and preserves the feed excerpt. With an LLM configured, it requests a short Russian digest and falls back to the local formatter if the API is unavailable.

## Quick start

Requirements: Python 3.11 or newer and a Telegram bot that is an administrator of the target channel.

### Install as an application

The recommended installation uses [pipx](https://pipx.pypa.io/), which keeps the application isolated and exposes the `nextlevel` command globally:

If `pipx` is not installed yet, install it once with `py -m pip install --user pipx` on Windows or your operating system's package manager.

```bash
pipx install https://github.com/Samopal88/nextlevel/archive/refs/heads/main.zip
nextlevel setup
```

The interactive setup asks for the BotFather token, channel ID, timezone, and posting times. It verifies the bot and its administrator access without publishing anything, saves the configuration outside the source code, and can enable automatic startup.

The two unavoidable Telegram steps are:

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Add that bot to the target channel as an administrator with permission to post.

Useful commands:

```bash
nextlevel preview             # build posts without publishing
nextlevel once                # publish one batch and exit
nextlevel run                 # run the foreground scheduler
nextlevel check               # validate saved settings
nextlevel config-path         # show where settings are stored
nextlevel autostart-enable    # enable background startup
nextlevel autostart-disable   # remove background startup
```

Update or uninstall the application with `pipx upgrade nextlevel-telegram-bot` and `pipx uninstall nextlevel-telegram-bot`.

### Run from source

```bash
git clone https://github.com/Samopal88/nextlevel.git
cd nextlevel
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` in `.env`, then validate the configuration:

```bash
python bot.py --check
```

Preview current posts without sending anything to Telegram:

```bash
python bot.py --dry-run
```

Publish one batch or start the scheduler:

```bash
python bot.py --once
python bot.py
```

On Windows PowerShell, activate the virtual environment with `.venv\Scripts\Activate.ps1`.

The installed application supports Windows Task Scheduler, Linux systemd user services, and macOS LaunchAgents for automatic startup. No administrator/root account is required in the normal case.

## Configuration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Live mode | — | Token from BotFather. |
| `TELEGRAM_CHANNEL_ID` | Live mode | — | Channel username such as `@nextlvlgm`, or a numeric chat ID. |
| `TIMEZONE` | No | `Europe/Warsaw` | IANA timezone used by the scheduler. |
| `POST_TIMES` | No | `10:00,19:00` | Comma-separated local times in 24-hour `HH:MM` format. |
| `MAX_POSTS_PER_RUN` | No | `5` | Maximum entries in one batch. |
| `HOURS_LOOKBACK` | No | `48` | Maximum age of feed entries. |
| `DATA_DIR` | No | `data` | Directory containing the deduplication state. |
| `REQUEST_TIMEOUT` | No | `15` | HTTP timeout in seconds. |
| `POST_DELAY_SECONDS` | No | `2` | Delay between Telegram posts. |
| `LOG_LEVEL` | No | `INFO` | Python log level. |
| `DRY_RUN` | No | `0` | Print posts instead of sending them. |
| `RUN_ONCE` | No | `0` | Publish one batch and exit; useful on cron platforms. |
| `LLM_API_KEY` | AI mode | — | API key for an OpenAI-compatible endpoint. |
| `LLM_BASE_URL` | No | `https://api.openai.com/v1` | API base URL, including `/v1`. |
| `LLM_MODEL` | AI mode | — | Model name passed to `/chat/completions`. |

`LLM_API_KEY` and `LLM_MODEL` must either both be set or both be empty. Never commit `.env`; it is ignored by Git.

## Docker

```bash
docker build -t nextlevel .
docker run --env-file .env -v nextlevel-data:/app/data nextlevel
```

The volume preserves `posted.json` across container replacements.

## Railway

The repository includes both `railway.json` and a `Procfile`.

1. Create a Railway project from this GitHub repository.
2. Add the variables from `.env.example`.
3. Attach a persistent volume mounted at `/app/data`.
4. Set `DATA_DIR=/app/data`.
5. Deploy; the start command is `python bot.py`.

Without a persistent volume, the bot can repost old links after a redeploy because its local state is ephemeral.

## Feeds

The default sources are PC Gamer, Polygon, GameSpot, Eurogamer, IGN, Anime News Network, and Anime Corner. Edit `FEEDS_GAMING` and `FEEDS_ANIME` in `bot.py` to change them.

Publishers retain ownership of their content. Next Level posts a short excerpt or generated digest and links back to the original article. Review each source's terms before running a public channel.

## Tests

```bash
python -m unittest discover -s tests -v
python -m py_compile bot.py
```

The same checks run in GitHub Actions for every push and pull request.

## Contributing

Bug reports and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a change.

If Next Level is useful to you, a genuine GitHub star helps other people discover it.
