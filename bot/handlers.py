import logging

import config
from telegram import Update
from telegram.ext import ContextTypes

from ai.gemini import summarize_news
from bot.formatter import format_weather_message
from news.rss import fetch_all_sources
from weather.cwa import WeatherLookupError, fetch_district_weather

logger = logging.getLogger(__name__)


async def weather_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    args = context.args
    district = args[0] if args else config.WEATHER_DISTRICTS[0]

    if config.CWA_API_KEY is None:
        await update.message.reply_text(
            '⚠️ 尚未設定 CWA_API_KEY，無法查詢天氣。',
            parse_mode='Markdown',
        )
        return

    try:
        weather = await fetch_district_weather(district, config.CWA_API_KEY)
        message = format_weather_message(weather)
    except WeatherLookupError as exc:
        logger.warning('Weather lookup failed for %s: %s', district, exc)
        message = f'⚠️ {exc}'
    except Exception as exc:
        logger.exception('Unexpected weather error for %s', district, exc_info=exc)
        message = f'⚠️ 無法取得 {district} 的天氣資訊，請稍後再試。'

    await update.message.reply_text(message, parse_mode='Markdown')


async def news_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if config.GEMINI_API_KEY is None:
        await update.message.reply_text(
            '⚠️ 尚未設定 GEMINI_API_KEY，無法整理新聞摘要。',
            parse_mode='Markdown',
        )
        return

    await update.message.reply_text(
        '⏳ 正在整理今日新聞，請稍候...',
        parse_mode='Markdown',
    )

    news_items = fetch_all_sources(limit_per_source=3)
    summary = summarize_news(news_items, config.GEMINI_API_KEY)

    await update.message.reply_text(summary, parse_mode='Markdown')
