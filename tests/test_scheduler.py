from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config


@pytest.mark.asyncio
async def test_send_morning_weather_sends_formatted_message() -> None:
    from scheduler.jobs import send_morning_weather

    bot = MagicMock()
    bot.send_message = AsyncMock()
    weather = MagicMock()

    with (
        patch(
            'scheduler.jobs.fetch_district_weather',
            AsyncMock(return_value=weather),
        ) as fetch_weather,
        patch(
            'scheduler.jobs.format_weather_message',
            return_value='早安天氣',
        ),
    ):
        await send_morning_weather(bot)

    fetch_weather.assert_awaited_once_with(
        config.WEATHER_DISTRICT,
        config.CWA_API_KEY,
    )
    bot.send_message.assert_awaited_once_with(
        chat_id=config.TELEGRAM_GROUP_ID,
        text='早安天氣',
        parse_mode='Markdown',
    )


@pytest.mark.asyncio
async def test_send_morning_weather_falls_back_on_error() -> None:
    from scheduler.jobs import send_morning_weather

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        'scheduler.jobs.fetch_district_weather',
        AsyncMock(side_effect=RuntimeError('boom')),
    ):
        await send_morning_weather(bot)

    bot.send_message.assert_awaited_once_with(
        chat_id=config.TELEGRAM_GROUP_ID,
        text='⚠️ 早報天氣資料暫時無法取得，請使用 /weather 手動查詢。',
        parse_mode='Markdown',
    )


def test_setup_scheduler_registers_morning_weather_job() -> None:
    from scheduler.jobs import setup_scheduler

    bot = MagicMock()

    scheduler = setup_scheduler(bot)
    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == 'morning_weather'
    assert jobs[0].args == (bot,)
    assert str(jobs[0].trigger) == (
        f"cron[hour='{config.MORNING_SEND_HOUR}', "
        f"minute='{config.MORNING_SEND_MINUTE}']"
    )
