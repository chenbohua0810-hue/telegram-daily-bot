from pathlib import Path

from kronos_trading_bot.cli import build_parser, main


def test_cli_parser_defaults_to_paper_mode():
    # Arrange
    parser = build_parser()

    # Act
    args = parser.parse_args(
        [
            "run-fixture",
            "--symbol",
            "BTC/USDT",
            "--fixture",
            "tests/fixtures/btcusdt_1h.csv",
        ]
    )

    # Assert
    assert args.command == "run-fixture"
    assert args.mode == "paper"


def test_cli_parser_exposes_no_live_mode_or_secret_flags():
    # Arrange
    parser = build_parser()

    # Act
    help_text = parser.format_help().lower()

    # Assert
    assert "live" not in help_text
    assert "api-key" not in help_text
    assert "secret" not in help_text
    assert "token" not in help_text


def test_cli_run_fixture_writes_report_and_returns_success(tmp_path, capsys):
    # Arrange
    fixture = Path(__file__).parent / "fixtures" / "btcusdt_1h.csv"

    # Act
    exit_code = main(
        [
            "run-fixture",
            "--symbol",
            "BTC/USDT",
            "--fixture",
            str(fixture),
            "--report-dir",
            str(tmp_path),
        ]
    )

    # Assert
    assert exit_code == 0
    assert (tmp_path / "latest_report.md").exists()
    output = capsys.readouterr().out
    assert "BTC/USDT" in output
    assert "live_orders_attempted=0" in output
