from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Callable

import ccxt
import pandas as pd

from models import Portfolio, Position, TradeDecision


# ---------------------------------------------------------------------------
# position_sizer
# ---------------------------------------------------------------------------


def compute_position_size(
    *,
    portfolio: Portfolio,
    asset_volatility: float,
    target_daily_vol: float = 0.02,
    max_position_pct: float = 0.10,
) -> Decimal:
    base = float(portfolio.total_value_usdt) * max_position_pct
    volatility_floor = max(asset_volatility, 0.005)
    vol_adj = target_daily_vol / volatility_floor
    raw = base * vol_adj
    return Decimal(str(min(raw, float(portfolio.cash_usdt))))


@dataclass(frozen=True)
class StopAction:
    symbol: str
    fraction: Decimal
    reason: str


def position_stop_check(
    position: Position,
    current_price: Decimal,
    btc_24h_change: float,
    *,
    now: datetime | None = None,
) -> StopAction | None:
    current_time = now or datetime.now(timezone.utc)
    entry_price = position.avg_entry_price
    if entry_price <= Decimal("0"):
        return None

    stop_threshold = Decimal("0.95") if btc_24h_change <= -0.10 else Decimal("0.92")
    stop_reason = "stop_loss_-5pct_market_regime" if btc_24h_change <= -0.10 else "stop_loss_-8pct"
    if current_price <= entry_price * stop_threshold:
        return StopAction(symbol=position.symbol, fraction=Decimal("1"), reason=stop_reason)

    peak_price = position.peak_price or max(entry_price, current_price)
    if peak_price >= entry_price * Decimal("1.20") and current_price <= peak_price * Decimal("0.70"):
        return StopAction(symbol=position.symbol, fraction=Decimal("1"), reason="trailing_stop")

    age = current_time - position.entry_time
    unrealized_pnl_pct = (current_price - entry_price) / entry_price
    if age >= timedelta(days=7):
        return StopAction(symbol=position.symbol, fraction=Decimal("1"), reason="max_hold_period")
    if age >= timedelta(hours=48) and unrealized_pnl_pct < Decimal("0.02"):
        return StopAction(symbol=position.symbol, fraction=Decimal("1"), reason="time_stop_no_progress")

    return None


# ---------------------------------------------------------------------------
# risk_guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    size_multiplier: float
    reasons: list[str]


def check_risk(
    *,
    new_symbol: str,
    new_size_usdt: Decimal,
    portfolio: Portfolio,
    correlation_provider: Callable[[str, list[str]], dict[str, float]],
    daily_pnl_pct: float,
    max_concurrent: int = 10,
    correlation_threshold: float = 0.8,
    daily_loss_circuit: float = -0.05,
) -> RiskCheckResult:
    reasons: list[str] = []
    size_multiplier = 1.0

    if len(portfolio.positions) >= max_concurrent:
        reasons.append("max_concurrent_reached")

    if daily_pnl_pct <= daily_loss_circuit:
        reasons.append("daily_loss_circuit")

    if reasons:
        return RiskCheckResult(passed=False, size_multiplier=0.0, reasons=reasons)

    correlations = correlation_provider(new_symbol, list(portfolio.positions))
    for symbol, correlation in correlations.items():
        if correlation > correlation_threshold:
            size_multiplier = 0.5
            reasons.append(f"high_correlation:{symbol}:{correlation:.2f}")

    return RiskCheckResult(passed=True, size_multiplier=size_multiplier, reasons=reasons)


# ---------------------------------------------------------------------------
# binance_executor
# ---------------------------------------------------------------------------


class NetworkError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    filled_quantity: Decimal
    avg_price: Decimal
    fee_usdt: Decimal
    pre_trade_mid_price: Decimal
    estimated_slippage_pct: float | None
    realized_slippage_pct: float | None
    estimated_fee_pct: float | None
    realized_fee_pct: float | None
    binance_order_id: str | None
    error: str | None


@dataclass(frozen=True)
class SymbolFilters:
    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal


class BinanceExecutor:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_trading: bool,
        *,
        exchange: Any | None = None,
        trades_repo: Any | None = None,
        record_trades: bool = True,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.exchange = exchange
        self.trades_repo = trades_repo
        self.record_trades = record_trades
        self._markets: set[str] = set()
        self._symbol_filters: dict[str, SymbolFilters] = {}

    async def load_markets(self) -> set[str]:
        markets = await self.exchange.load_markets()
        self._markets = {symbol for symbol in markets if symbol.endswith("/USDT")}
        self._symbol_filters = {
            symbol: _extract_symbol_filters(market)
            for symbol, market in markets.items()
            if symbol.endswith("/USDT")
        }
        return set(self._markets)

    async def fetch_price(self, symbol: str) -> Decimal:
        ticker = await self.exchange.fetch_ticker(symbol)
        return Decimal(str(ticker["last"]))

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> pd.DataFrame:
        rows = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]]

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> dict:
        return await self.exchange.fetch_order_book(symbol, limit=limit)

    async def execute(
        self,
        decision: TradeDecision,
        *,
        estimated_slippage_pct: float | None = None,
        estimated_fee_pct: float | None = None,
    ) -> ExecutionResult:
        price = await self.fetch_price(decision.symbol)
        quantity = self._quantize_quantity(
            decision.symbol,
            Decimal(str(decision.quantity_usdt)) / price,
            price,
        )
        orderbook = await self.fetch_orderbook(decision.symbol)
        pre_trade_mid_price = _mid_price(orderbook)
        if quantity <= Decimal("0"):
            return _failed_execution_result(
                pre_trade_mid_price=pre_trade_mid_price,
                estimated_slippage_pct=estimated_slippage_pct,
                estimated_fee_pct=estimated_fee_pct,
                error="min_notional_not_met",
            )

        if self.paper_trading:
            return await self._execute_paper(
                decision=decision,
                quantity=quantity,
                pre_trade_mid_price=pre_trade_mid_price,
                estimated_slippage_pct=estimated_slippage_pct,
                estimated_fee_pct=estimated_fee_pct,
            )

        return await self._execute_live(
            decision=decision,
            quantity=quantity,
            pre_trade_mid_price=pre_trade_mid_price,
            estimated_slippage_pct=estimated_slippage_pct,
            estimated_fee_pct=estimated_fee_pct,
        )

    async def execute_exit(
        self,
        symbol: str,
        fraction: Decimal,
        *,
        position: Position | None = None,
        source_wallet: str = "",
        reason: str = "mirror_exit",
    ) -> ExecutionResult:
        if not Decimal("0") < fraction <= Decimal("1"):
            raise ValueError("fraction must be greater than 0 and less than or equal to 1")

        exit_position = position or self._find_position(symbol)
        if exit_position is None:
            return ExecutionResult(
                success=False,
                filled_quantity=Decimal("0"),
                avg_price=Decimal("0"),
                fee_usdt=Decimal("0"),
                pre_trade_mid_price=Decimal("0"),
                estimated_slippage_pct=None,
                realized_slippage_pct=None,
                estimated_fee_pct=None,
                realized_fee_pct=None,
                binance_order_id=None,
                error="position_not_found",
            )

        orderbook = await self.fetch_orderbook(symbol)
        pre_trade_mid_price = _mid_price(orderbook)
        quantity = self._quantize_quantity(
            symbol,
            exit_position.quantity * fraction,
            pre_trade_mid_price,
        )
        if quantity <= Decimal("0"):
            return _failed_execution_result(
                pre_trade_mid_price=pre_trade_mid_price,
                estimated_slippage_pct=None,
                estimated_fee_pct=None,
                error="min_notional_not_met",
            )
        decision = TradeDecision(
            action="sell",
            symbol=symbol,
            quantity_usdt=float(quantity * pre_trade_mid_price),
            confidence=100,
            reasoning=reason[:200],
            source_wallet=source_wallet or exit_position.source_wallet,
        )

        if self.paper_trading:
            return await self._execute_paper(
                decision=decision,
                quantity=quantity,
                pre_trade_mid_price=pre_trade_mid_price,
                estimated_slippage_pct=None,
                estimated_fee_pct=None,
            )

        return await self._execute_live(
            decision=decision,
            quantity=quantity,
            pre_trade_mid_price=pre_trade_mid_price,
            estimated_slippage_pct=None,
            estimated_fee_pct=None,
        )

    def _find_position(self, symbol: str) -> Position | None:
        if self.trades_repo is None or not hasattr(self.trades_repo, "get_positions"):
            return None

        positions = self.trades_repo.get_positions()
        for position in positions:
            if position.symbol == symbol:
                return position
        return None

    def _quantize(self, symbol: str, quantity: Decimal, price: Decimal) -> tuple[Decimal, Decimal]:
        filters = self._symbol_filters.get(symbol)
        if filters is None:
            return Decimal("0"), price

        quantized_quantity = _round_to_step(quantity, filters.step_size)
        quantized_price = _round_to_step(price, filters.tick_size)
        if quantized_quantity * quantized_price < filters.min_notional:
            return Decimal("0"), quantized_price
        return quantized_quantity, quantized_price

    def _quantize_quantity(self, symbol: str, quantity: Decimal, price: Decimal) -> Decimal:
        quantized_quantity, _ = self._quantize(symbol, quantity, price)
        return quantized_quantity

    async def fetch_portfolio(self) -> Portfolio:
        balance = await self.exchange.fetch_balance()
        positions = {}
        if self.trades_repo is not None and hasattr(self.trades_repo, "get_positions"):
            positions = {position.symbol: position for position in self.trades_repo.get_positions()}

        cash_usdt = Decimal(str(balance.get("free", {}).get("USDT", 0)))
        total_value = cash_usdt
        return Portfolio(
            cash_usdt=cash_usdt,
            positions=positions,
            total_value_usdt=total_value,
            daily_pnl_pct=0.0,
        )

    async def _execute_paper(
        self,
        *,
        decision: TradeDecision,
        quantity: Decimal,
        pre_trade_mid_price: Decimal,
        estimated_slippage_pct: float | None,
        estimated_fee_pct: float | None,
    ) -> ExecutionResult:
        fee_usdt = Decimal(str(decision.quantity_usdt)) * Decimal("0.00075")
        realized_fee_pct = float(fee_usdt / Decimal(str(decision.quantity_usdt)))
        await self._record_trade(
            decision=decision,
            quantity=quantity,
            avg_price=pre_trade_mid_price,
            fee_usdt=fee_usdt,
            status="paper",
            paper_trading=True,
            binance_order_id=None,
            pre_trade_mid_price=pre_trade_mid_price,
            estimated_slippage_pct=estimated_slippage_pct,
            realized_slippage_pct=0.0,
            estimated_fee_pct=estimated_fee_pct,
            realized_fee_pct=realized_fee_pct,
        )
        return ExecutionResult(
            success=True,
            filled_quantity=quantity,
            avg_price=pre_trade_mid_price,
            fee_usdt=fee_usdt,
            pre_trade_mid_price=pre_trade_mid_price,
            estimated_slippage_pct=estimated_slippage_pct,
            realized_slippage_pct=0.0,
            estimated_fee_pct=estimated_fee_pct,
            realized_fee_pct=realized_fee_pct,
            binance_order_id=None,
            error=None,
        )

    async def _execute_live(
        self,
        *,
        decision: TradeDecision,
        quantity: Decimal,
        pre_trade_mid_price: Decimal,
        estimated_slippage_pct: float | None,
        estimated_fee_pct: float | None,
    ) -> ExecutionResult:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                order = await self._create_market_order(decision, quantity)
                avg_price = Decimal(str(order.get("average") or pre_trade_mid_price))
                fee_usdt = Decimal(str(order.get("fee", {}).get("cost", 0)))
                realized_slippage_pct = _realized_slippage(
                    action=decision.action,
                    avg_price=avg_price,
                    pre_trade_mid_price=pre_trade_mid_price,
                )
                realized_fee_pct = float(fee_usdt / Decimal(str(decision.quantity_usdt)))
                await self._record_trade(
                    decision=decision,
                    quantity=quantity,
                    avg_price=avg_price,
                    fee_usdt=fee_usdt,
                    status="filled",
                    paper_trading=False,
                    binance_order_id=order.get("id"),
                    pre_trade_mid_price=pre_trade_mid_price,
                    estimated_slippage_pct=estimated_slippage_pct,
                    realized_slippage_pct=realized_slippage_pct,
                    estimated_fee_pct=estimated_fee_pct,
                    realized_fee_pct=realized_fee_pct,
                )
                return ExecutionResult(
                    success=True,
                    filled_quantity=quantity,
                    avg_price=avg_price,
                    fee_usdt=fee_usdt,
                    pre_trade_mid_price=pre_trade_mid_price,
                    estimated_slippage_pct=estimated_slippage_pct,
                    realized_slippage_pct=realized_slippage_pct,
                    estimated_fee_pct=estimated_fee_pct,
                    realized_fee_pct=realized_fee_pct,
                    binance_order_id=order.get("id"),
                    error=None,
                )
            except (NetworkError, ccxt.NetworkError, ccxt.RequestTimeout) as error:
                last_error = error

        await self._record_trade(
            decision=decision,
            quantity=Decimal("0"),
            avg_price=Decimal("0"),
            fee_usdt=Decimal("0"),
            status="failed",
            paper_trading=False,
            binance_order_id=None,
            pre_trade_mid_price=None,
            estimated_slippage_pct=None,
            realized_slippage_pct=None,
            estimated_fee_pct=None,
            realized_fee_pct=None,
        )
        return ExecutionResult(
            success=False,
            filled_quantity=Decimal("0"),
            avg_price=Decimal("0"),
            fee_usdt=Decimal("0"),
            pre_trade_mid_price=pre_trade_mid_price,
            estimated_slippage_pct=estimated_slippage_pct,
            realized_slippage_pct=None,
            estimated_fee_pct=estimated_fee_pct,
            realized_fee_pct=None,
            binance_order_id=None,
            error=str(last_error) if last_error is not None else "unknown_error",
        )

    async def _create_market_order(self, decision: TradeDecision, quantity: Decimal) -> dict:
        if decision.action == "buy":
            return await self.exchange.create_market_buy_order(decision.symbol, float(quantity))
        return await self.exchange.create_market_sell_order(decision.symbol, float(quantity))

    async def _record_trade(
        self,
        *,
        decision: TradeDecision,
        quantity: Decimal,
        avg_price: Decimal,
        fee_usdt: Decimal,
        status: str,
        paper_trading: bool,
        binance_order_id: str | None,
        pre_trade_mid_price: Decimal | None,
        estimated_slippage_pct: float | None,
        realized_slippage_pct: float | None,
        estimated_fee_pct: float | None,
        realized_fee_pct: float | None,
    ) -> None:
        if self.trades_repo is None or not self.record_trades:
            return

        record_trade = self.trades_repo.record_trade
        kwargs = {
            "symbol": decision.symbol,
            "action": decision.action,
            "quantity": quantity,
            "price": avg_price,
            "fee_usdt": fee_usdt,
            "source_wallet": decision.source_wallet,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "status": status,
            "paper_trading": paper_trading,
            "binance_order_id": binance_order_id,
            "pre_trade_mid_price": pre_trade_mid_price,
            "estimated_slippage_pct": estimated_slippage_pct,
            "realized_slippage_pct": realized_slippage_pct,
            "estimated_fee_pct": estimated_fee_pct,
            "realized_fee_pct": realized_fee_pct,
        }
        if hasattr(record_trade, "__call__"):
            result = record_trade(**kwargs)
            if hasattr(result, "__await__"):
                await result

def _extract_symbol_filters(market: dict[str, Any]) -> SymbolFilters:
    filters = _filters_by_type(market)
    lot_size = filters.get("LOT_SIZE", {})
    price_filter = filters.get("PRICE_FILTER", {})
    min_notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
    return SymbolFilters(
        step_size=_positive_decimal(lot_size.get("stepSize"), Decimal("0.00000001")),
        tick_size=_positive_decimal(price_filter.get("tickSize"), Decimal("0.00000001")),
        min_notional=_extract_min_notional(market, min_notional),
    )


def _filters_by_type(market: dict[str, Any]) -> dict[str, dict[str, Any]]:
    filters = market.get("info", {}).get("filters", [])
    return {
        str(item.get("filterType")): item
        for item in filters
        if isinstance(item, dict) and item.get("filterType") is not None
    }


def _extract_min_notional(market: dict[str, Any], filter_data: dict[str, Any]) -> Decimal:
    limits = market.get("limits", {})
    cost_limits = limits.get("cost", {}) if isinstance(limits, dict) else {}
    fallback = cost_limits.get("min") if isinstance(cost_limits, dict) else None
    value = filter_data.get("minNotional") or filter_data.get("notional") or fallback
    return _positive_decimal(value, Decimal("0"))


def _positive_decimal(value: Any, fallback: Decimal) -> Decimal:
    if value is None:
        return fallback
    parsed = Decimal(str(value))
    if parsed <= Decimal("0"):
        return fallback
    return parsed


def _round_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= Decimal("0"):
        return value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return (value // step) * step


def _failed_execution_result(
    *,
    pre_trade_mid_price: Decimal,
    estimated_slippage_pct: float | None,
    estimated_fee_pct: float | None,
    error: str,
) -> ExecutionResult:
    return ExecutionResult(
        success=False,
        filled_quantity=Decimal("0"),
        avg_price=Decimal("0"),
        fee_usdt=Decimal("0"),
        pre_trade_mid_price=pre_trade_mid_price,
        estimated_slippage_pct=estimated_slippage_pct,
        realized_slippage_pct=None,
        estimated_fee_pct=estimated_fee_pct,
        realized_fee_pct=None,
        binance_order_id=None,
        error=error,
    )


def _mid_price(orderbook: dict) -> Decimal:
    if not orderbook.get("bids") or not orderbook.get("asks"):
        raise ValueError("Empty orderbook bids/asks")
    best_bid = Decimal(str(orderbook["bids"][0][0]))
    best_ask = Decimal(str(orderbook["asks"][0][0]))
    return (best_bid + best_ask) / Decimal("2")


def _realized_slippage(*, action: str, avg_price: Decimal, pre_trade_mid_price: Decimal) -> float:
    signed = Decimal("1") if action == "buy" else Decimal("-1")
    value = signed * (avg_price - pre_trade_mid_price) / pre_trade_mid_price
    return float(value)
