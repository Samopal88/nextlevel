# syntax=docker/dockerfile:1
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV TIMEZONE=Europe/Warsaw POST_TIMES=10:00,19:00 MAX_POSTS_PER_RUN=5 HOURS_LOOKBACK=48 DATA_DIR=data
CMD ["python", "bot.py"]
