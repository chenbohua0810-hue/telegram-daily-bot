from __future__ import annotations

from datetime import datetime, timezone
import sys
import time
from zoneinfo import ZoneInfo

from .config import Config, ConfigError
from .digest import build_digest_message, enrich_news_items, fetch_news_items, filter_recent_items, pick_top_items
from .gemini import GeminiNewsEnricher
from .scheduler import next_daily_run, seconds_until
from .telegram import send_telegram_message


def run_once(config: Config) -> None:
    print("INFO fetching public technology news feeds", flush=True)
    items = fetch_news_items(config.rss_urls)
    recent_items = filter_recent_items(items, now=datetime.now(timezone.utc), hours=24)
    selected = pick_top_items(recent_items, limit=config.item_limit)
    enricher = None
    if config.translate_titles and config.gemini_api_key:
        print(f"INFO enriching titles and article key points with {config.translation_model}", flush=True)
        enricher = GeminiNewsEnricher(api_key=config.gemini_api_key, model=config.translation_model)
    elif config.translate_titles:
        print("WARN TRANSLATE_TITLES is enabled but GEMINI_API_KEY is missing; using source titles", flush=True)
    entries = enrich_news_items(selected, enricher=enricher)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(config.timezone_name)).date()
    message = build_digest_message(entries, today=today)
    send_telegram_message(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        text=message,
    )
    print(f"INFO sent {len(selected)} news items to Telegram chat_id={config.telegram_chat_id}", flush=True)


def run_forever(config: Config) -> None:
    while True:
        run_at = next_daily_run(
            now_utc=datetime.now(timezone.utc),
            hour=config.send_hour,
            minute=config.send_minute,
            timezone_name=config.timezone_name,
        )
        wait_seconds = seconds_until(run_at)
        print(f"INFO next run at {run_at.isoformat()} ({wait_seconds:.0f}s)", flush=True)
        time.sleep(wait_seconds)
        run_once(config)


def main() -> int:
    try:
        config = Config.from_env()
        if config.run_once:
            run_once(config)
        else:
            run_forever(config)
        return 0
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("INFO interrupted", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
