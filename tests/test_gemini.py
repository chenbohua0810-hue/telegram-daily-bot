from unittest.mock import MagicMock, patch

from news.rss import NewsItem
from news.throk import TrendingPost

NEWS_ITEMS = [
    NewsItem(
        title='台灣 GDP 成長',
        url='https://example.com/1',
        summary='台灣第一季GDP成長5.2%',
        source='ltn',
    ),
    NewsItem(
        title='AI 新突破',
        url='https://example.com/2',
        summary='Google 發布 Gemini 2.0',
        source='bbc',
    ),
]

TRENDING_POSTS = [
    TrendingPost(
        text='台灣科技產業話題',
        engagement=2000,
        url='https://threads.net/p/abc',
    ),
]


def test_summarize_news_returns_string():
    from ai.gemini import summarize_news

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text='📰 今日新聞摘要\n1. 台灣 GDP 成長...'
    )

    with patch('ai.gemini.genai.Client', return_value=mock_client):
        result = summarize_news(NEWS_ITEMS, TRENDING_POSTS, 'test_key')

    assert isinstance(result, str)
    assert len(result) > 0
    mock_client.models.generate_content.assert_called_once()


def test_summarize_news_returns_fallback_on_error():
    from ai.gemini import summarize_news

    with patch('ai.gemini.genai.Client', side_effect=Exception('API error')):
        result = summarize_news(NEWS_ITEMS, TRENDING_POSTS, 'test_key')

    assert '台灣 GDP 成長' in result
    assert 'AI 新突破' in result
