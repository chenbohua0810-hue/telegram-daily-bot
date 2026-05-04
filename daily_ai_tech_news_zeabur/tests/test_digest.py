from datetime import datetime, timezone, timedelta

import pytest

from daily_ai_tech_news.config import Config, ConfigError
from daily_ai_tech_news.digest import DigestEntry, NewsItem, build_digest_message, enrich_news_items, filter_ai_items, filter_recent_items, pick_top_items
from daily_ai_tech_news.scheduler import next_daily_run


def test_filter_ai_items_keeps_only_ai_related_news():
    # Arrange
    items = [
        NewsItem(title="OpenAI releases new agent model", link="https://example.com/ai", source="AIWire", published_at=None, summary="Agentic AI workflow update"),
        NewsItem(title="Nvidia announces AI accelerator supply plan", link="https://example.com/chip", source="ChipNews", published_at=None, summary="GPU demand for model training"),
        NewsItem(title="Cloud database pricing changes", link="https://example.com/cloud", source="CloudWire", published_at=None, summary="Cloud cost update"),
        NewsItem(title="Apple refreshes MacBook colors", link="https://example.com/apple", source="GadgetWire", published_at=None, summary="New colors and storage tiers"),
    ]

    # Act
    filtered = filter_ai_items(items)

    # Assert
    assert [item.link for item in filtered] == ["https://example.com/ai", "https://example.com/chip"]


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
        "https://example.com/chip",
        "https://example.com/ai",
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

def test_enrich_news_items_uses_model_output_for_traditional_chinese_title_and_article_point():
    # Arrange
    class FakeEnricher:
        def enrich_item(self, item):
            return DigestEntry(
                title="OpenAI 發表新的代理模型",
                key_point="新模型主打工具使用與低延遲，瞄準企業工作流程導入。",
            )

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
    enriched = enrich_news_items(items, enricher=FakeEnricher())

    # Assert
    assert enriched == [
        DigestEntry(
            title="OpenAI 發表新的代理模型",
            key_point="新模型主打工具使用與低延遲，瞄準企業工作流程導入。",
        )
    ]


def test_build_digest_message_only_sends_traditional_chinese_title_and_article_key_points():
    # Arrange
    today = datetime(2026, 5, 5, tzinfo=timezone(timedelta(hours=8))).date()
    entries = [
        DigestEntry(
            title="OpenAI 發表新的代理模型",
            key_point="新模型主打工具使用與低延遲，瞄準企業工作流程導入。",
        )
    ]

    # Act
    message = build_digest_message(entries, today=today)

    # Assert
    assert "今日 AI 新聞重點（2026-05-05）" in message
    assert "1. 標題：OpenAI 發表新的代理模型" in message
    assert "重點：新模型主打工具使用與低延遲，瞄準企業工作流程導入。" in message
    assert "這則新聞與" not in message
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


def test_config_defaults_to_higher_quality_gemini_model(monkeypatch):
    # Arrange
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.delenv("TRANSLATION_MODEL", raising=False)

    # Act
    config = Config.from_env()

    # Assert
    assert config.translation_model == "gemini-2.5-flash"


def test_config_upgrades_legacy_flash_lite_model(monkeypatch):
    # Arrange
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setenv("TRANSLATION_MODEL", "gemini-2.5-flash-lite")

    # Act
    config = Config.from_env()

    # Assert
    assert config.translation_model == "gemini-2.5-flash"


def test_next_daily_run_uses_asia_taipei_eight_am():
    # Arrange
    now = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)

    # Act
    run_at = next_daily_run(now_utc=now, hour=8, minute=0, timezone_name="Asia/Taipei")

    # Assert
    assert run_at.isoformat() == "2026-05-05T08:00:00+08:00"
