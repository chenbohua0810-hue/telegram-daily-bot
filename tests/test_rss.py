import pytest
from unittest.mock import MagicMock, patch

from news.rss import NewsItem, fetch_rss_news

MOCK_FEED = MagicMock()
MOCK_FEED.entries = [
    MagicMock(
        title='台灣經濟成長超預期',
        link='https://example.com/1',
        summary='台灣第一季GDP成長達5.2%...',
        published='Mon, 13 Apr 2026 08:00:00 +0800',
    ),
    MagicMock(
        title='AI 科技新突破',
        link='https://example.com/2',
        summary='Google 發布新模型...',
        published='Mon, 13 Apr 2026 07:30:00 +0800',
    ),
]


def test_fetch_rss_news_returns_news_items():
    with patch('news.rss.feedparser.parse', return_value=MOCK_FEED):
        results = fetch_rss_news('https://fake-rss.com/feed.xml', limit=2)

    assert len(results) == 2
    assert isinstance(results[0], NewsItem)
    assert results[0].title == '台灣經濟成長超預期'
    assert results[0].url == 'https://example.com/1'
    assert 'GDP' in results[0].summary


def test_fetch_rss_news_respects_limit():
    with patch('news.rss.feedparser.parse', return_value=MOCK_FEED):
        results = fetch_rss_news('https://fake-rss.com/feed.xml', limit=1)

    assert len(results) == 1


def test_fetch_all_sources_aggregates_results():
    with patch('news.rss.feedparser.parse', return_value=MOCK_FEED):
        from news.rss import fetch_all_sources

        results = fetch_all_sources(limit_per_source=1)

    assert len(results) >= 1
    assert all(isinstance(item, NewsItem) for item in results)
