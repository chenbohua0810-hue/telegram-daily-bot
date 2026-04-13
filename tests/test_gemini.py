from unittest.mock import MagicMock, patch

from news.rss import NewsItem

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


def test_summarize_news_returns_string():
    from ai.gemini import summarize_news

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text='📰 今日新聞摘要\n1. 台灣 GDP 成長...'
    )

    with patch('ai.gemini.genai.Client', return_value=mock_client):
        result = summarize_news(NEWS_ITEMS, 'test_key')

    assert isinstance(result, str)
    assert len(result) > 0
    mock_client.models.generate_content.assert_called_once()


def test_summarize_news_returns_fallback_on_error():
    from ai.gemini import summarize_news

    with patch('ai.gemini.genai.Client', side_effect=Exception('API error')):
        result = summarize_news(NEWS_ITEMS, 'test_key')

    assert '台灣 GDP 成長' in result
    assert 'AI 新突破' in result
