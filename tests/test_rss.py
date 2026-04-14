from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news.rss import NewsItem, fetch_rss_news

MOCK_FEED = MagicMock()
MOCK_FEED.entries = [
    MagicMock(
        title='台灣經濟成長超預期',
        link='https://example.com/1',
        summary='台灣第一季GDP成長達5.2%...',
    ),
    MagicMock(
        title='AI 科技新突破',
        link='https://example.com/2',
        summary='Google 發布新模型...',
    ),
]

MOCK_RESPONSE = MagicMock(text='<rss/>', status_code=200)
MOCK_RESPONSE.raise_for_status = MagicMock()


@pytest.mark.asyncio
async def test_fetch_rss_news_returns_news_items():
    with (
        patch('news.rss.httpx.AsyncClient') as mock_client_cls,
        patch('news.rss.feedparser.parse', return_value=MOCK_FEED),
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MOCK_RESPONSE)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        results = await fetch_rss_news('https://fake-rss.com/feed.xml', limit=2)

    assert len(results) == 2
    assert isinstance(results[0], NewsItem)
    assert results[0].title == '台灣經濟成長超預期'
    assert results[0].url == 'https://example.com/1'
    assert 'GDP' in results[0].summary


@pytest.mark.asyncio
async def test_fetch_rss_news_respects_limit():
    with (
        patch('news.rss.httpx.AsyncClient') as mock_client_cls,
        patch('news.rss.feedparser.parse', return_value=MOCK_FEED),
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MOCK_RESPONSE)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        results = await fetch_rss_news('https://fake-rss.com/feed.xml', limit=1)

    assert len(results) == 1


@pytest.mark.asyncio
async def test_fetch_all_sources_aggregates_results():
    from news.rss import fetch_all_sources

    mock_item = NewsItem(title='t', url='u', summary='s', source='src')

    with patch('news.rss.fetch_rss_news', AsyncMock(return_value=[mock_item])):
        results = await fetch_all_sources(limit_per_source=1)

    assert len(results) >= 1
    assert all(isinstance(item, NewsItem) for item in results)


@pytest.mark.asyncio
async def test_fetch_all_sources_skips_failed_sources():
    from news.rss import fetch_all_sources

    mock_item = NewsItem(title='t', url='u', summary='s', source='src')
    call_count = 0

    async def _side_effect(url, limit):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError('timeout')
        return [mock_item]

    with patch('news.rss.fetch_rss_news', side_effect=_side_effect):
        results = await fetch_all_sources(limit_per_source=1)

    assert len(results) >= 1
