from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str
    PAPER_TRADING: bool = True

    ANTHROPIC_API_KEY: str
    AI_SCORER_MODEL: str = "claude-haiku-4-5-20251001"

    LLM_PRIMARY_NAME: Literal["groq", "nvidia", "ollama"] = "groq"
    LLM_PRIMARY_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_PRIMARY_MODEL: str = "llama-3.3-70b-versatile"
    LLM_PRIMARY_API_KEY: str

    LLM_SECONDARY_NAME: str | None = None
    LLM_SECONDARY_BASE_URL: str | None = None
    LLM_SECONDARY_MODEL: str | None = None
    LLM_SECONDARY_API_KEY: str | None = None

    ETHERSCAN_API_KEY: str
    SOLSCAN_API_KEY: str
    BSCSCAN_API_KEY: str = ""

    CRYPTOPANIC_API_KEY: str = ""

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    MIN_TRADE_USD: float = 10000.0
    MAX_POSITION_PCT: float = 0.10
    DAILY_LOSS_CIRCUIT: float = -0.05
    MAX_CONCURRENT_POSITIONS: int = 10
    POLL_INTERVAL_SECONDS: int = 60
    AI_SCORER_CONFIDENCE_THRESHOLD: int = 60

    HIGH_VALUE_USD_THRESHOLD: float = 50_000.0
    P1_HIGH_TRUST_MIN_USD: float = 20_000.0
    P1_HIGH_TRUST_RECENT_WINRATE: float = 0.60

    BATCH_WINDOW_SECONDS: int = 5
    BATCH_MAX_SIZE: int = 5
    BATCH_MAX_INPUT_TOKENS: int = 6000

    USE_WEBSOCKET: bool = True
    ETH_WSS_URL: str = ""
    SOL_WSS_URL: str = ""
    BSC_WSS_URL: str = ""
    WS_HEARTBEAT_TIMEOUT_SECONDS: int = 60
    WS_RECONNECT_BACKOFF_CAP_SECONDS: int = 60

    ADDRESSES_DB_PATH: str = "data/addresses.db"
    TRADES_DB_PATH: str = "data/trades.db"
    EVENTS_LOG_PATH: str = "data/events.jsonl"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
