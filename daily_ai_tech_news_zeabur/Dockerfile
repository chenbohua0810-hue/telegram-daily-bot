FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Taipei \
    PYTHONPATH=/app/src

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser
COPY pyproject.toml ./
COPY src ./src

USER appuser

CMD ["python", "-m", "daily_ai_tech_news.main"]
