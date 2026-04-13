from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import news_command, weather_command
from weather.cwa import WeatherLookupError


@pytest.mark.asyncio
async def test_weather_command_sends_message() -> None:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    mock_weather = MagicMock()
    mock_weather.district = '大安區'
    mock_weather.description = '晴天'
    mock_weather.max_temp = 28
    mock_weather.min_temp = 20
    mock_weather.rain_prob = 10

    with (
        patch(
            'bot.handlers.fetch_district_weather',
            AsyncMock(return_value=mock_weather),
        ),
        patch(
            'bot.handlers.format_weather_message',
            return_value='天氣訊息',
        ),
    ):
        await weather_command(update, context)

    update.message.reply_text.assert_called_once_with(
        '天氣訊息',
        parse_mode='Markdown',
    )


@pytest.mark.asyncio
async def test_weather_command_returns_lookup_error_message() -> None:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ['文山區']

    with patch(
        'bot.handlers.fetch_district_weather',
        AsyncMock(side_effect=WeatherLookupError('查無 文山區 的天氣資料。')),
    ):
        await weather_command(update, context)

    update.message.reply_text.assert_called_once_with(
        '⚠️ 查無 文山區 的天氣資料。',
        parse_mode='Markdown',
    )


@pytest.mark.asyncio
async def test_news_command_sends_message() -> None:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with (
        patch('bot.handlers.fetch_all_sources', return_value=[]),
        patch('bot.handlers.summarize_news', return_value='📰 今日新聞'),
    ):
        await news_command(update, context)

    update.message.reply_text.assert_any_call(
        '📰 今日新聞',
        parse_mode='Markdown',
    )


@pytest.mark.asyncio
async def test_news_command_returns_fallback_when_gemini_not_configured() -> None:
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with (
        patch('bot.handlers.config.GEMINI_API_KEY', None),
        patch('bot.handlers.fetch_all_sources', return_value=[]),
    ):
        await news_command(update, context)

    update.message.reply_text.assert_any_call(
        '⚠️ 尚未設定 GEMINI_API_KEY，無法整理新聞摘要。',
        parse_mode='Markdown',
    )
