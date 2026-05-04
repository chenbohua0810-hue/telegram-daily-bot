from __future__ import annotations

from dataclasses import dataclass
import os


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


DEFAULT_RSS_URLS = (
    "https://news.google.com/rss/search?q=AI%20OR%20artificial%20intelligence%20technology&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.feedburner.com/TechCrunch/",
    "https://www.theverge.com/rss/index.xml",
    "https://hnrss.org/frontpage",
)


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    rss_urls: tuple[str, ...]
    timezone_name: str = "Asia/Taipei"
    send_hour: int = 8
    send_minute: int = 0
    item_limit: int = 5
    run_once: bool = False
    gemini_api_key: str = ""
    translation_model: str = "gemini-2.5-flash-lite"
    translate_titles: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        token = _required_env("TELEGRAM_BOT_TOKEN")
        chat_id = _required_env("TELEGRAM_CHAT_ID")
        rss_urls = tuple(
            url.strip()
            for url in os.getenv("NEWS_RSS_URLS", "\n".join(DEFAULT_RSS_URLS)).replace(",", "\n").splitlines()
            if url.strip()
        )
        if not rss_urls:
            raise ConfigError("NEWS_RSS_URLS must contain at least one RSS URL")

        return cls(
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
            rss_urls=rss_urls,
            timezone_name=os.getenv("TZ", "Asia/Taipei"),
            send_hour=_int_env("SEND_HOUR", 8, minimum=0, maximum=23),
            send_minute=_int_env("SEND_MINUTE", 0, minimum=0, maximum=59),
            item_limit=_int_env("ITEM_LIMIT", 5, minimum=1, maximum=10),
            run_once=os.getenv("RUN_ONCE", "").lower() in {"1", "true", "yes"},
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            translation_model=os.getenv("TRANSLATION_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite",
            translate_titles=os.getenv("TRANSLATE_TITLES", "true").lower() not in {"0", "false", "no"},
        )


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value
