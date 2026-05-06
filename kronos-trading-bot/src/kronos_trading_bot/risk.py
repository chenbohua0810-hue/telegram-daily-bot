from __future__ import annotations

from typing import Any

from kronos_trading_bot.domain import RiskDecision


def evaluate_order_intent(
    intent: dict[str, Any],
    portfolio: dict[str, Any],
    policy: dict[str, Any],
    *,
    data_quality_passed: bool,
    model_is_stale: bool,
) -> RiskDecision:
    if (
        policy.get("mode") == "live"
        or intent.get("mode") == "live"
        or policy.get("allow_live_trading") is True
    ):
        return _reject("live_trading_rejected")
    if policy.get("mode") != "paper" or intent.get("mode") != "paper":
        return _reject("non_paper_mode_rejected")
    if not data_quality_passed:
        return _reject("data_quality_failed")
    if model_is_stale:
        return _reject("stale_model")

    symbol = intent["symbol"]
    if symbol not in policy.get("allowed_symbols", []):
        return _reject("unsupported_symbol")

    equity = float(portfolio["equity_usdt"])
    starting_day_equity = float(portfolio["starting_day_equity_usdt"])
    max_daily_loss_pct = float(policy["max_daily_loss_pct"])
    if (starting_day_equity - equity) / starting_day_equity > max_daily_loss_pct:
        return _reject("max_daily_loss_exceeded")

    open_positions = portfolio.get("open_positions", {})
    if symbol not in open_positions and len(open_positions) >= int(
        policy["max_open_positions"]
    ):
        return _reject("max_open_positions_reached")
    if symbol in open_positions and policy.get("pyramiding_enabled") is False:
        return _reject("pyramiding_rejected")

    if policy.get("require_stop_loss") is True and intent.get("stop_loss") is None:
        return _reject("missing_stop_loss")

    notional = float(intent["notional_usdt"])
    max_position_notional = equity * float(policy["max_single_position_pct"])
    if notional > max_position_notional:
        return _reject("max_single_position_exceeded")

    return RiskDecision(
        approved=True,
        reason_code="approved",
        adjusted_notional_usdt=notional,
    )


def _reject(reason_code: str) -> RiskDecision:
    return RiskDecision(
        approved=False,
        reason_code=reason_code,
        adjusted_notional_usdt=None,
    )
