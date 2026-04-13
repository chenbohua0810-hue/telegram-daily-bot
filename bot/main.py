import logging

from telegram.ext import Application, CommandHandler

import config
from bot.handlers import news_command, weather_command
from scheduler.jobs import setup_scheduler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    scheduler = setup_scheduler(application.bot)
    scheduler.start()
    logger.info(
        'Scheduler started. Morning weather at %02d:%02d Asia/Taipei',
        config.MORNING_SEND_HOUR,
        config.MORNING_SEND_MINUTE,
    )


def main() -> None:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler('weather', weather_command))
    app.add_handler(CommandHandler('news', news_command))

    logger.info('Bot starting...')
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
