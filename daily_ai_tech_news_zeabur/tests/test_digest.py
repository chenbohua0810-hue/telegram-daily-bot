from datetime import datetime, timezone, timedelta

import pytest

from daily_ai_tech_news.config import Config, ConfigError
from daily_ai_tech_news.digest import NewsItem, build_digest_message, filter_recent_items, pick_top_items
from daily_ai_tech_news.scheduler import next_daily_run


def test_pick_top_items_prioritizes_ai_and_deduplicates_links():
    # Arrange
    items = [
        NewsItem(title="Cloud database pricing changes", link="https://example.com/cloud", source="CloudWire", published_at=None, summary="Cloud cost update"),
        NewsItem(title="OpenAI releases new agent model", link="https://example.com/ai", source="AIWire", published_at=None, summary="Agent model update"),
        NewsItem(title="Nvidia announces AI chip supply plan", link="https://example.com/chip", source="ChipNews", published_at=None, summary="AI accelerator supply"),
        NewsItem(title="Duplicate OpenAI mirror", link="https://example.com/ai", source="Mirror", published_at=None, summary="Duplicate"),
    ]

    # Act
    selected = pick_top_items(items, limit=3)

    # Assert
    assert [item.link for item in selected] == [
        "https://example.com/ai",
        "https://example.com/chip",
        "https://example.com/cloud",
    ]


def test_filter_recent_items_keeps_only_past_24_hours_and_undated_items():
    # Arrange
    now = datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)
    items = [
        NewsItem(title="Recent AI update", link="https://example.com/recent", source="AIWire", published_at=now - timedelta(hours=2), summary="Recent"),
        NewsItem(title="Boundary chip update", link="https://example.com/boundary", source="ChipNews", published_at=now - timedelta(hours=24), summary="Boundary"),
        NewsItem(title="Old cloud update", link="https://example.com/old", source="CloudWire", published_at=now - timedelta(hours=25), summary="Old"),
        NewsItem(title="Undated RSS item", link="https://example.com/undated", source="RSS", published_at=None, summary="No date in feed"),
    ]

    # Act
    recent = filter_recent_items(items, now=now, hours=24)

    # Assert
    assert [item.link for item in recent] == [
        "https://example.com/recent",
        "https://example.com/boundary",
        "https://example.com/undated",
    ]

def test_build_digest_message_only_sends_traditional_chinese_title_and_key_points():
    # Arrange
    today = datetime(2026, 5, 5, tzinfo=timezone(timedelta(hours=8))).date()
    items = [
        NewsItem(
            title="OpenAI releases new agent model",
            link="https://example.com/ai",
            source="AIWire",
            published_at=None,
            summary="A new agent model focuses on tool use and lower latency for business workflows.",
        )
    ]

    # Act
    message = build_digest_message(items, today=today)

    # Assert
    assert "今日 AI / 科技新聞重點（2026-05-05）" in message
    assert "1. 標題：OpenAI releases new agent model" in message
    assert "重點：" in message
    assert "今日重點：" in message
    assert "分類：" not in message
    assert "來源：" not in message
    assert "為什麼重要：" not in message
    assert "https://example.com/ai" not in message
    assert len(message) < 4096


def test_config_requires_telegram_secret_without_exposing_value(monkeypatch):
    # Arrange
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

    # Act / Assert
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        Config.from_env()


def test_next_daily_run_uses_asia_taipei_eight_am():
    # Arrange
    now = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)

    # Act
    run_at = next_daily_run(now_utc=now, hour=8, minute=0, timezone_name="Asia/Taipei")

    # Assert
    assert run_at.isoformat() == "2026-05-05T08:00:00+08:00"
