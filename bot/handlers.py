import config
from telegram import Update
from telegram.ext import ContextTypes

from ai.gemini import summarize_news
from bot.formatter import format_weather_message
from news.rss import fetch_all_sources
from news.throk import fetch_trending_threads
from weather.cwa import fetch_district_weather


async def weather_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    args = context.args
    district = args[0] if args else config.WEATHER_DISTRICT

    try:
        weather = await fetch_district_weather(district, config.CWA_API_KEY)
        message = format_weather_message(weather)
    except Exception:
        message = f'⚠️ 無法取得 {district} 的天氣資訊，請稍後再試。'

    await update.message.reply_text(message, parse_mode='Markdown')


async def news_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.message.reply_text(
        '⏳ 正在整理今日新聞，請稍候...',
        parse_mode='Markdown',
    )

    news_items = fetch_all_sources(limit_per_source=3)
    trending = await fetch_trending_threads(config.THROK_API_KEY, limit=3)
    summary = summarize_news(news_items, trending, config.GEMINI_API_KEY)

    await update.message.reply_text(summary, parse_mode='Markdown')
