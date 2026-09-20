# Next Level

[![CI](https://github.com/Samopal88/nextlevel/actions/workflows/ci.yml/badge.svg)](https://github.com/Samopal88/nextlevel/actions/workflows/ci.yml)
[![Telegram](https://img.shields.io/badge/Telegram-%40nextlvlgm-26A5E4?logo=telegram&logoColor=white)](https://t.me/nextlvlgm)

**Next Level** — компактный бот для автоматической публикации игровых и аниме-новостей в Telegram. Он собирает свежие записи из RSS, убирает повторы, находит изображения и публикует посты по расписанию.

[English README](README.md) · [Канал Next Level](https://t.me/nextlvlgm)

## Что умеет бот

- Читает семь игровых и аниме-источников.
- Работает по нескольким временам публикации в выбранном часовом поясе.
- Отбирает только свежие записи и не публикует один URL дважды.
- Ищет изображение в RSS, HTML записи и метаданных Open Graph.
- Если Telegram не принимает картинку, повторяет отправку текстом.
- По желанию переписывает материал на русском через любой OpenAI-совместимый `/chat/completions` API.
- Без LLM использует локальное форматирование и исходный RSS-фрагмент.
- Поддерживает безопасный предпросмотр, Docker и Railway.

## Быстрый запуск

Нужны Python 3.11+ и Telegram-бот с правами администратора канала.

```bash
git clone https://github.com/Samopal88/nextlevel.git
cd nextlevel
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните в `.env` переменные `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHANNEL_ID`.

```bash
python bot.py --check     # проверить настройки
python bot.py --dry-run   # показать посты, ничего не отправляя
python bot.py --once      # опубликовать одну подборку
python bot.py             # запустить постоянное расписание
```

В Windows PowerShell виртуальное окружение включается командой `.venv\Scripts\Activate.ps1`.

## Основные настройки

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Токен от BotFather. Нужен для реальной публикации. |
| `TELEGRAM_CHANNEL_ID` | — | Например, `@nextlvlgm` или числовой ID канала. |
| `TIMEZONE` | `Europe/Warsaw` | Часовой пояс расписания. |
| `POST_TIMES` | `10:00,19:00` | Время публикаций через запятую. |
| `MAX_POSTS_PER_RUN` | `5` | Максимум постов за один запуск. |
| `HOURS_LOOKBACK` | `48` | Максимальный возраст новости в часах. |
| `DATA_DIR` | `data` | Каталог файла `posted.json`. |
| `REQUEST_TIMEOUT` | `15` | Таймаут HTTP-запросов. |
| `POST_DELAY_SECONDS` | `2` | Пауза между публикациями. |
| `LLM_API_KEY` | — | Ключ OpenAI-совместимого API. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Базовый URL API вместе с `/v1`. |
| `LLM_MODEL` | — | Имя модели для `/chat/completions`. |

Все параметры перечислены в [.env.example](.env.example). `LLM_API_KEY` и `LLM_MODEL` задаются только вместе. Файл `.env` нельзя добавлять в Git.

## Docker

```bash
docker build -t nextlevel .
docker run --env-file .env -v nextlevel-data:/app/data nextlevel
```

Том `nextlevel-data` сохраняет историю опубликованных ссылок после перезапуска контейнера.

## Railway

1. Создайте проект из этого GitHub-репозитория.
2. Добавьте переменные из `.env.example`.
3. Подключите постоянный том к `/app/data`.
4. Установите `DATA_DIR=/app/data`.
5. Запустите deploy — команда старта уже задана как `python bot.py`.

Без постоянного тома файл истории исчезнет при redeploy, и старые новости могут опубликоваться повторно.

## Проверка изменений

```bash
python -m unittest discover -s tests -v
python -m py_compile bot.py
```

Те же проверки автоматически выполняются в GitHub Actions.

Источники сохраняют права на свои материалы. Бот публикует короткий фрагмент или пересказ и обязательно оставляет ссылку на оригинал.
