from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
import pytz

import config
from bot.formatter import format_weather_message
from weather.cwa import fetch_district_weather

TZ = pytz.timezone('Asia/Taipei')


async def send_morning_weather(bot: Bot) -> None:
    try:
        weather = await fetch_district_weather(
            config.WEATHER_DISTRICT,
            config.CWA_API_KEY,
        )
        message = format_weather_message(weather)
    except Exception:
        message = '⚠️ 早報天氣資料暫時無法取得，請使用 /weather 手動查詢。'

    await bot.send_message(
        chat_id=config.TELEGRAM_GROUP_ID,
        text=message,
        parse_mode='Markdown',
    )


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(
        send_morning_weather,
        trigger='cron',
        hour=config.MORNING_SEND_HOUR,
        minute=config.MORNING_SEND_MINUTE,
        args=[bot],
        id='morning_weather',
        replace_existing=True,
    )
    return scheduler
