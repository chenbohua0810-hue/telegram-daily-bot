from pathlib import Path

from kronos_trading_bot.pipeline import run_fixture_cycle


def test_runs_one_full_cycle_for_btc_fixture_without_secrets(tmp_path):
    # Arrange
    fixture = Path(__file__).parent / "fixtures" / "btcusdt_1h.csv"

    # Act
    result = run_fixture_cycle(
        symbol="BTC/USDT",
        fixture_path=fixture,
        report_dir=tmp_path,
    )

    # Assert
    assert result.status in {"completed", "no_trade"}
    assert result.symbol == "BTC/USDT"
    assert result.live_orders_attempted == 0
    assert result.report_path == tmp_path / "latest_report.md"
    report = result.report_path.read_text(encoding="utf-8")
    assert "BTC/USDT" in report
    assert "live_orders_attempted: 0" in report
    assert "api_key" not in report.lower()
    assert "secret" not in report.lower()
    assert "token" not in report.lower()


def test_runs_one_full_cycle_for_eth_fixture_without_live_orders(tmp_path):
    # Arrange
    fixture = Path(__file__).parent / "fixtures" / "ethusdt_1h.csv"

    # Act
    result = run_fixture_cycle(
        symbol="ETH/USDT",
        fixture_path=fixture,
        report_dir=tmp_path,
    )

    # Assert
    assert result.status in {"completed", "no_trade"}
    assert result.symbol == "ETH/USDT"
    assert result.live_orders_attempted == 0
    assert result.report_path.exists()


def test_validation_failure_stops_safely_and_still_writes_report(tmp_path):
    # Arrange
    fixture = tmp_path / "invalid_btcusdt_1h.csv"
    fixture.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-01-01T00:00:00+00:00,100.0,102.0,99.0,101.0,10.0\n"
        "2026-01-01T00:00:00+00:00,101.0,103.0,100.0,102.0,11.0\n",
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports"

    # Act
    result = run_fixture_cycle(
        symbol="BTC/USDT",
        fixture_path=fixture,
        report_dir=report_dir,
    )

    # Assert
    assert result.status == "validation_failed"
    assert result.live_orders_attempted == 0
    report = result.report_path.read_text(encoding="utf-8")
    assert "validation_failed" in report
    assert "duplicated_timestamps" in report
    assert "forecast_attempted: false" in report
    assert "paper_trader_attempted: false" in report
