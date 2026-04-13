from unittest.mock import AsyncMock, MagicMock, call, patch

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
        ),
        patch(
            'scheduler.jobs.format_weather_message',
            return_value='早安天氣',
        ),
    ):
        await send_morning_weather(bot)

    expected_text = '\n\n'.join(['早安天氣'] * len(config.WEATHER_DISTRICTS))
    bot.send_message.assert_awaited_once_with(
        chat_id=config.TELEGRAM_GROUP_ID,
        text=expected_text,
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

    sent_text = bot.send_message.call_args.kwargs['text']
    for district in config.WEATHER_DISTRICTS:
        assert district in sent_text


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
