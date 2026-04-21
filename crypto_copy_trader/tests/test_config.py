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
}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
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

    settings = get_settings()

    assert settings.MIN_TRADE_USD == 5000.0
