from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kronos_trading_bot.data_validation import validate_candles
from kronos_trading_bot.forecast import run_forecast
from kronos_trading_bot.paper import PaperPortfolio, simulate_buy
from kronos_trading_bot.reports import write_cycle_report
from kronos_trading_bot.risk import evaluate_order_intent
from kronos_trading_bot.signals import build_signal


@dataclass(frozen=True)
class PipelineResult:
    symbol: str
    status: str
    live_orders_attempted: int
    report_path: Path


class _FixtureForecaster:
    model_name = "fixture-trend-forecaster"
    tokenizer_name = "none"

    def predict(self, candles: list[dict[str, Any]], pred_len: int) -> list[dict[str, Any]]:
        latest = candles[-1]
        return [
            {
                "timestamp": latest["timestamp"] + timedelta(hours=pred_len),
                "close": latest["close"] * 1.03,
            }
        ]


def run_fixture_cycle(
    *,
    symbol: str,
    fixture_path: Path,
    report_dir: Path,
) -> PipelineResult:
    candles = _load_candles_csv(fixture_path)
    latest = candles[-1]
    quality = validate_candles(
        candles,
        now=latest["timestamp"] + timedelta(minutes=30),
        max_delay=timedelta(minutes=90),
        symbol=symbol,
    )

    if not quality.passed:
        report_path = write_cycle_report(
            report_dir,
            symbol=symbol,
            status="validation_failed",
            live_orders_attempted=0,
            details={
                "errors": ",".join(quality.errors),
                "forecast_attempted": False,
                "paper_trader_attempted": False,
            },
        )
        return PipelineResult(symbol, "validation_failed", 0, report_path)

    forecast = run_forecast(_FixtureForecaster(), candles, pred_len=1)
    prediction = forecast.predictions[0]
    signal = build_signal(
        symbol,
        latest_close=latest["close"],
        predicted_close=prediction["close"],
        entry_threshold=0.02,
        exit_threshold=-0.01,
        model_name=forecast.model_name,
        timestamp=prediction["timestamp"],
    )

    status = "no_trade"
    paper_trader_attempted = False
    if signal.action == "BUY":
        portfolio = PaperPortfolio.initial(cash_usdt=10_000)
        intent = {
            "mode": "paper",
            "symbol": symbol,
            "notional_usdt": 1000,
            "stop_loss": latest["close"] * 0.98,
        }
        risk = evaluate_order_intent(
            intent,
            {
                "equity_usdt": portfolio.cash_usdt,
                "starting_day_equity_usdt": portfolio.cash_usdt,
                "open_positions": dict(portfolio.positions),
            },
            {
                "mode": "paper",
                "allow_live_trading": False,
                "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
                "max_daily_loss_pct": 0.03,
                "max_open_positions": 2,
                "pyramiding_enabled": False,
                "require_stop_loss": True,
                "max_single_position_pct": 0.10,
            },
            data_quality_passed=quality.passed,
            model_is_stale=False,
        )
        if risk.approved:
            paper_trader_attempted = True
            simulate_buy(
                portfolio,
                symbol=symbol,
                notional_usdt=risk.adjusted_notional_usdt or 0.0,
                market_price=latest["close"],
                fee_rate=0.001,
                slippage_bps=10,
            )
            status = "completed"

    report_path = write_cycle_report(
        report_dir,
        symbol=symbol,
        status=status,
        live_orders_attempted=0,
        details={
            "candle_count": quality.candle_count,
            "forecast_attempted": True,
            "forecast_model": forecast.model_name,
            "paper_trader_attempted": paper_trader_attempted,
            "signal_action": signal.action,
            "signal_reason": signal.reason_code,
        },
    )
    return PipelineResult(symbol, status, 0, report_path)


def _load_candles_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            {
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for row in csv.DictReader(handle)
        ]
