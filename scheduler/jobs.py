from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
import pytz
import logging

import config
from bot.formatter import format_weather_message
from weather.cwa import fetch_district_weather

TZ = pytz.timezone('Asia/Taipei')
logger = logging.getLogger(__name__)


async def send_morning_weather(bot: Bot) -> None:
    if config.TELEGRAM_GROUP_ID is None or config.CWA_API_KEY is None:
        logger.warning(
            'Skipping morning weather send: TELEGRAM_GROUP_ID or CWA_API_KEY is not configured.'
        )
        return

    parts = []
    for district in config.WEATHER_DISTRICTS:
        try:
            weather = await fetch_district_weather(district, config.CWA_API_KEY)
            parts.append(format_weather_message(weather))
        except Exception:
            parts.append(f'⚠️ 無法取得 {district} 的天氣資訊。')

    message = '\n\n'.join(parts) if parts else '⚠️ 早報天氣資料暫時無法取得，請使用 /weather 手動查詢。'

    await bot.send_message(
        chat_id=config.TELEGRAM_GROUP_ID,
        text=message,
        parse_mode='Markdown',
    )


def setup_scheduler(bot: Bot) -> AsyncIOScheduler | None:
    if config.TELEGRAM_GROUP_ID is None or config.CWA_API_KEY is None:
        logger.warning(
            'Scheduler disabled: TELEGRAM_GROUP_ID or CWA_API_KEY is not configured.'
        )
        return None

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
