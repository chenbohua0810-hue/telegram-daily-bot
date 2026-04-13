from unittest.mock import MagicMock, patch


def test_main_builds_application_and_registers_handlers() -> None:
    from bot.main import main

    builder = MagicMock()
    application = MagicMock()
    builder.token.return_value = builder
    builder.post_init.return_value = builder
    builder.build.return_value = application

    with (
        patch('bot.main.Application.builder', return_value=builder),
        patch('bot.main.CommandHandler', side_effect=lambda name, fn: (name, fn)),
    ):
        main()

    builder.token.assert_called_once()
    builder.post_init.assert_called_once()
    builder.build.assert_called_once_with()
    assert application.add_handler.call_count == 2
    application.run_polling.assert_called_once_with(drop_pending_updates=True)


def test_post_init_starts_scheduler() -> None:
    from bot.main import post_init

    application = MagicMock()
    scheduler = MagicMock()

    with patch('bot.main.setup_scheduler', return_value=scheduler) as setup:
        import asyncio

        asyncio.run(post_init(application))

    setup.assert_called_once_with(application.bot)
    scheduler.start.assert_called_once_with()
