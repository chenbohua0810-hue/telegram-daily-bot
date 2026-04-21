from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from models.decision import TradeDecision
from models.portfolio import Portfolio


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


class BinanceExecutor:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper_trading: bool,
        *,
        exchange: Any | None = None,
        trades_repo: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.exchange = exchange
        self.trades_repo = trades_repo
        self._markets: set[str] = set()

    async def load_markets(self) -> set[str]:
        markets = await self.exchange.load_markets()
        self._markets = {symbol for symbol in markets if symbol.endswith("/USDT")}
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
        quantity = (Decimal(str(decision.quantity_usdt)) / price).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_HALF_UP,
        )
        orderbook = await self.fetch_orderbook(decision.symbol)
        pre_trade_mid_price = _mid_price(orderbook)

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
            except NetworkError as error:
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
        if self.trades_repo is None:
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


def _mid_price(orderbook: dict) -> Decimal:
    best_bid = Decimal(str(orderbook["bids"][0][0]))
    best_ask = Decimal(str(orderbook["asks"][0][0]))
    return (best_bid + best_ask) / Decimal("2")


def _realized_slippage(*, action: str, avg_price: Decimal, pre_trade_mid_price: Decimal) -> float:
    signed = Decimal("1") if action == "buy" else Decimal("-1")
    value = signed * (avg_price - pre_trade_mid_price) / pre_trade_mid_price
    return float(value)
