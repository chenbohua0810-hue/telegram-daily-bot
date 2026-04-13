import pytest
from unittest.mock import AsyncMock, patch

from news.throk import TrendingPost, fetch_trending_threads


@pytest.mark.asyncio
async def test_fetch_trending_threads_returns_posts():
    mock_response = {
        'data': [
            {'text': 'AI 科技話題引發討論', 'engagement': 1500, 'url': 'https://threads.net/p/abc'},
            {'text': '台灣選舉最新動態', 'engagement': 1200, 'url': 'https://threads.net/p/def'},
        ]
    }

    with patch('news.throk.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )
        )
        results = await fetch_trending_threads('test_key', limit=2)

    assert len(results) == 2
    assert isinstance(results[0], TrendingPost)
    assert results[0].text == 'AI 科技話題引發討論'
    assert results[0].engagement == 1500


@pytest.mark.asyncio
async def test_fetch_trending_threads_returns_empty_on_error():
    with patch('news.throk.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception('API unavailable')
        )
        results = await fetch_trending_threads('test_key', limit=3)

    assert results == []
