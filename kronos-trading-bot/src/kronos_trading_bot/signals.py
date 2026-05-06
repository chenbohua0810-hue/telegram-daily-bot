from __future__ import annotations

from datetime import datetime

from kronos_trading_bot.domain import Signal, SignalAction


def build_signal(
    symbol: str,
    *,
    latest_close: float,
    predicted_close: float,
    entry_threshold: float,
    exit_threshold: float,
    model_name: str,
    confidence_score: float = 1.0,
    timestamp: datetime | None = None,
) -> Signal:
    predicted_return = round((predicted_close - latest_close) / latest_close, 10)
    action = SignalAction.HOLD
    reason_code = "predicted_return_weak"
    if predicted_return >= entry_threshold:
        action = SignalAction.BUY
        reason_code = "predicted_return_above_entry_threshold"
    elif predicted_return <= exit_threshold:
        action = SignalAction.SELL_TO_CLOSE
        reason_code = "predicted_return_below_exit_threshold"

    return Signal(
        symbol=symbol,
        action=action,
        predicted_return=predicted_return,
        confidence_score=confidence_score,
        model_used=model_name,
        reason_code=reason_code,
        timestamp=timestamp,
    )
