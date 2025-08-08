# Next Level Telegram Autopost Bot (Railway-ready)

- Парсит игровые + аниме-новости из RSS
- Картинки тянет из статьи (media/og:image)
- Переписывает кратко в стиле Next Level (3–5 предложений)
- Постит по расписанию (10:00, 19:00 по Europe/Warsaw по умолчанию)

## Railway Deploy (коротко)

1) Зальй это в GitHub (репозиторий с этими файлами).
2) На https://railway.app → New Project → Deploy from GitHub → выбери репо.
3) В Variables добавь:
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHANNEL_ID (напр. @nextlvlgm)
   - TIMEZONE=Europe/Warsaw
   - POST_TIMES=10:00,19:00
   - MAX_POSTS_PER_RUN=5
   - HOURS_LOOKBACK=48
   - DATA_DIR=data
4) Start Command: `python bot.py`
5) Deploy.

RUN_ONCE=1 — для разового теста.

## Локально

```bash
pip install -r requirements.txt
RUN_ONCE=1 python bot.py   # разовый пост прямо сейчас
python bot.py              # далее по расписанию
```

## Источники

- PC Gamer, Polygon, GameSpot, Eurogamer, IGN
- Anime News Network, Anime Corner
Правь список в `bot.py`.
