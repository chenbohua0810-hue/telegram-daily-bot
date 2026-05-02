from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import get_settings


REQUIRED_ENV = {
    "BINANCE_API_KEY": "binance-key",
    "BINANCE_API_SECRET": "binance-secret",
    "ANTHROPIC_API_KEY": "anthropic-key",
    "ETHERSCAN_API_KEY": "etherscan-key",
    "SOLSCAN_API_KEY": "solscan-key",
    "BSCSCAN_API_KEY": "bscscan-key",
    "CRYPTOPANIC_API_KEY": "cryptopanic-key",
    "TELEGRAM_BOT_TOKEN": "telegram-token",
    "TELEGRAM_CHAT_ID": "telegram-chat-id",
    "LLM_PRIMARY_API_KEY": "primary-key",
}


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_missing_required_env_raises(
    monkeypatch: pytest.MonkeyPatch,
    required_env: None,
) -> None:
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        get_settings()


def test_paper_trading_defaults_true(
    monkeypatch: pytest.MonkeyPatch,
    required_env: None,
) -> None:
    monkeypatch.delenv("PAPER_TRADING", raising=False)

    settings = get_settings()

    assert settings.PAPER_TRADING is True


def test_paper_trading_parses_false(
    monkeypatch: pytest.MonkeyPatch,
    required_env: None,
) -> None:
    monkeypatch.setenv("PAPER_TRADING", "false")

    settings = get_settings()

    assert settings.PAPER_TRADING is False


def test_numeric_fields_cast(
    monkeypatch: pytest.MonkeyPatch,
    required_env: None,
) -> None:
    monkeypatch.setenv("MIN_TRADE_USD", "5000")
    monkeypatch.setenv("BATCH_WINDOW_SECONDS", "7")
    monkeypatch.setenv("BATCH_MAX_SIZE", "4")
    monkeypatch.setenv("BATCH_MAX_INPUT_TOKENS", "7000")
    monkeypatch.setenv("HIGH_VALUE_USD_THRESHOLD", "75000")
    monkeypatch.setenv("P1_HIGH_TRUST_MIN_USD", "25000")
    monkeypatch.setenv("P1_HIGH_TRUST_RECENT_WINRATE", "0.75")
    monkeypatch.setenv("WS_HEARTBEAT_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("WS_RECONNECT_BACKOFF_CAP_SECONDS", "120")

    settings = get_settings()

    assert settings.MIN_TRADE_USD == 5000.0
    assert settings.BATCH_WINDOW_SECONDS == 7
    assert settings.BATCH_MAX_SIZE == 4
    assert settings.BATCH_MAX_INPUT_TOKENS == 7000
    assert settings.HIGH_VALUE_USD_THRESHOLD == 75000.0
    assert settings.P1_HIGH_TRUST_MIN_USD == 25000.0
    assert settings.P1_HIGH_TRUST_RECENT_WINRATE == 0.75
    assert settings.WS_HEARTBEAT_TIMEOUT_SECONDS == 90
    assert settings.WS_RECONNECT_BACKOFF_CAP_SECONDS == 120


def test_llm_routing_defaults(
    monkeypatch: pytest.MonkeyPatch,
    required_env: None,
) -> None:
    monkeypatch.delenv("LLM_PRIMARY_NAME", raising=False)
    monkeypatch.delenv("LLM_PRIMARY_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("LLM_SECONDARY_NAME", raising=False)
    monkeypatch.delenv("LLM_SECONDARY_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_SECONDARY_MODEL", raising=False)
    monkeypatch.delenv("LLM_SECONDARY_API_KEY", raising=False)
    monkeypatch.delenv("USE_WEBSOCKET", raising=False)
    monkeypatch.delenv("ETH_WSS_URL", raising=False)
    monkeypatch.delenv("SOL_WSS_URL", raising=False)
    monkeypatch.delenv("BSC_WSS_URL", raising=False)

    settings = get_settings()

    assert settings.LLM_PRIMARY_NAME == "groq"
    assert settings.LLM_PRIMARY_BASE_URL == "https://api.groq.com/openai/v1"
    assert settings.LLM_PRIMARY_MODEL == "llama-3.3-70b-versatile"
    assert settings.LLM_SECONDARY_NAME is None
    assert settings.LLM_SECONDARY_BASE_URL is None
    assert settings.LLM_SECONDARY_MODEL is None
    assert settings.LLM_SECONDARY_API_KEY is None
    assert settings.USE_WEBSOCKET is True
    assert settings.ETH_WSS_URL == ""
    assert settings.SOL_WSS_URL == ""
    assert settings.BSC_WSS_URL == ""


def test_websocket_and_secondary_fields_parse(
    monkeypatch: pytest.MonkeyPatch,
    required_env: None,
) -> None:
    monkeypatch.setenv("LLM_PRIMARY_NAME", "nvidia")
    monkeypatch.setenv("LLM_PRIMARY_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("LLM_PRIMARY_MODEL", "meta/llama-3.1-70b-instruct")
    monkeypatch.setenv("LLM_SECONDARY_NAME", "ollama")
    monkeypatch.setenv("LLM_SECONDARY_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_SECONDARY_MODEL", "llama3.1:8b")
    monkeypatch.setenv("LLM_SECONDARY_API_KEY", "secondary-key")
    monkeypatch.setenv("USE_WEBSOCKET", "false")
    monkeypatch.setenv("ETH_WSS_URL", "wss://eth.example")
    monkeypatch.setenv("SOL_WSS_URL", "wss://sol.example")
    monkeypatch.setenv("BSC_WSS_URL", "wss://bsc.example")

    settings = get_settings()

    assert settings.LLM_PRIMARY_NAME == "nvidia"
    assert settings.LLM_PRIMARY_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert settings.LLM_PRIMARY_MODEL == "meta/llama-3.1-70b-instruct"
    assert settings.LLM_SECONDARY_NAME == "ollama"
    assert settings.LLM_SECONDARY_BASE_URL == "http://localhost:11434/v1"
    assert settings.LLM_SECONDARY_MODEL == "llama3.1:8b"
    assert settings.LLM_SECONDARY_API_KEY == "secondary-key"
    assert settings.USE_WEBSOCKET is False
    assert settings.ETH_WSS_URL == "wss://eth.example"
    assert settings.SOL_WSS_URL == "wss://sol.example"
    assert settings.BSC_WSS_URL == "wss://bsc.example"
