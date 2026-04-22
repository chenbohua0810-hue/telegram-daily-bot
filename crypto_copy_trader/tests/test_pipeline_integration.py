from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from analysis.trade_logger import TradeLogger
from execution.binance_executor import ExecutionResult
from execution.risk_guard import RiskCheckResult
from main import PipelineDeps, process_event
from models.events import OnChainEvent
from models.portfolio import Portfolio
from models.signals import (
    SentimentCounts,
    SentimentSignal,
    TechnicalIndicators,
    TechnicalSignal,
    WalletScore,
)
from signals.ai_scorer import AIScore
from signals.slippage_fee import CostEstimate
from storage.addresses_repo import AddressesRepo
from storage.trades_repo import TradesRepo


def build_wallet(
    *,
    address: str = "0xabc123",
    status: str = "active",
) -> WalletScore:
    return WalletScore(
        address=address,
        chain="eth",
        win_rate=0.68,
        trade_count=80,
        max_drawdown=0.18,
        funds_usd=150000.0,
        recent_win_rate=0.71,
        trust_level="high",
        status=status,
    )


def build_event(
    *,
    wallet: str = "0xabc123",
    tx_hash: str = "tx-happy",
    amount_usd: str = "15000",
) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet=wallet,
        tx_hash=tx_hash,
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("5"),
        amount_usd=Decimal(amount_usd),
        raw={"block_number": 100},
    )


def build_portfolio() -> Portfolio:
    return Portfolio(
        cash_usdt=Decimal("50000"),
        positions={},
        total_value_usdt=Decimal("100000"),
        daily_pnl_pct=0.0,
    )


def build_technicals() -> tuple[TechnicalSignal, TechnicalIndicators]:
    return (
        TechnicalSignal(
            trend="bullish",
            momentum="bullish",
            volatility="medium",
            stat_arb="breakout",
            confidence=0.8,
        ),
        TechnicalIndicators(
            ema8=101.0,
            ema21=99.0,
            rsi=60.0,
            macd_hist=1.2,
            atr=2.1,
            atr_pct=0.02,
            bb_zscore=2.1,
            close_price=102.0,
        ),
    )


def build_sentiment() -> tuple[SentimentSignal, SentimentCounts]:
    return (
        SentimentSignal(signal="bullish", score=0.72, source_count=12),
        SentimentCounts(positive=8, negative=2, neutral=2, mention_delta=0.25),
    )


def build_ai_score(*, confidence: int = 82, recommendation: str = "execute") -> AIScore:
    return AIScore(
        confidence_score=confidence,
        reasoning="訊號堆疊一致，適合跟單。",
        recommendation=recommendation,
    )


def build_cost(*, total_cost_pct: float = 0.003) -> CostEstimate:
    return CostEstimate(
        slippage_pct=0.0015,
        fee_pct=0.0015,
        total_cost_pct=total_cost_pct,
        expected_profit_pct=0.04,
    )


def build_result() -> ExecutionResult:
    return ExecutionResult(
        success=True,
        filled_quantity=Decimal("1.0"),
        avg_price=Decimal("2500"),
        fee_usdt=Decimal("0.75"),
        pre_trade_mid_price=Decimal("2499"),
        estimated_slippage_pct=0.0015,
        realized_slippage_pct=0.0,
        estimated_fee_pct=0.0015,
        realized_fee_pct=0.00075,
        binance_order_id=None,
        error=None,
    )


class FakeExecutor:
    def __init__(self) -> None:
        self.fetch_price = AsyncMock(return_value=Decimal("62000"))
        self.fetch_ohlcv = AsyncMock(return_value=pd.DataFrame({"close": [1]}))
        self.fetch_orderbook = AsyncMock(return_value={"bids": [[2498, 5]], "asks": [[2500, 5]]})
        self.execute = AsyncMock(return_value=build_result())


def build_deps(tmp_path, monkeypatch: pytest.MonkeyPatch) -> tuple[PipelineDeps, TradesRepo]:
    addresses_repo = AddressesRepo(str(tmp_path / "addresses.db"))
    trades_repo = TradesRepo(str(tmp_path / "trades.db"))
    trade_logger = TradeLogger(trades_repo)
    executor = FakeExecutor()
    notifier = SimpleNamespace(
        notify_trade_fill=AsyncMock(),
        notify_trade_skip=AsyncMock(),
        notify_daily_summary=AsyncMock(),
        notify_risk_alert=AsyncMock(),
    )
    deps = PipelineDeps(
        settings=SimpleNamespace(
            MIN_TRADE_USD=10000.0,
            MAX_POSITION_PCT=0.10,
            DAILY_LOSS_CIRCUIT=-0.05,
            MAX_CONCURRENT_POSITIONS=10,
            AI_SCORER_CONFIDENCE_THRESHOLD=60,
            AI_SCORER_MODEL="claude-haiku-4-5-20251001",
            CRYPTOPANIC_API_KEY="cryptopanic",
        ),
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        executor=executor,
        anthropic=SimpleNamespace(),
        notifier=notifier,
        trade_logger=trade_logger,
        http=SimpleNamespace(),
        binance_symbols={"ETH/USDT", "BTC/USDT"},
        recent_events_cache=[],
        btc_24h_vol_pct=0.031,
        correlation_provider=lambda new_symbol, existing_symbols: {},
    )
    monkeypatch.setattr("main.compute_technicals", Mock(return_value=build_technicals()))
    monkeypatch.setattr("main.compute_sentiment", AsyncMock(return_value=build_sentiment()))
    monkeypatch.setattr("main.score_signal", AsyncMock(return_value=build_ai_score()))
    monkeypatch.setattr(
        "main.check_risk",
        Mock(return_value=RiskCheckResult(passed=True, size_multiplier=1.0, reasons=[])),
    )
    monkeypatch.setattr("main.estimate_cost", Mock(return_value=build_cost()))
    monkeypatch.setattr("main.should_reject", Mock(return_value=False))
    return deps, trades_repo


@pytest.mark.asyncio
async def test_pipeline_happy_path_executes_trade(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet())

    await process_event(build_event(), build_portfolio(), 0.0, deps)

    trades = trades_repo.recent_trades(hours=24)
    snapshots = trades_repo.get_snapshots(limit=10)
    assert len(trades) == 1
    assert trades[0]["status"] == "paper"
    assert len(snapshots) == 1
    assert snapshots[0].final_action == "buy"
    assert snapshots[0].trade_id is not None
    assert snapshots[0].trade_id == trades[0]["id"]


@pytest.mark.asyncio
async def test_pipeline_quant_filter_short_circuits_but_logs_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet())
    technicals = Mock(return_value=build_technicals())
    monkeypatch.setattr("main.compute_technicals", technicals)
    monkeypatch.setattr("main.quant_filter", Mock(return_value=(False, "below_min_trade_usd")))

    await process_event(build_event(amount_usd="500"), build_portfolio(), 0.0, deps)

    technicals.assert_not_called()
    snapshots = trades_repo.get_snapshots(limit=10)
    assert len(snapshots) == 1
    assert snapshots[0].final_action == "skip"
    assert snapshots[0].skip_reason == "below_min_trade_usd"
    assert snapshots[0].technical is None
    assert snapshots[0].sentiment is None
    assert snapshots[0].ai_confidence is None
    assert snapshots[0].risk is None
    assert snapshots[0].cost is None


@pytest.mark.asyncio
async def test_pipeline_ai_scorer_below_threshold_skips(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet())
    monkeypatch.setattr("main.score_signal", AsyncMock(return_value=build_ai_score(confidence=55)))

    await process_event(build_event(tx_hash="tx-low-ai"), build_portfolio(), 0.0, deps)

    snapshots = trades_repo.get_snapshots(limit=10)
    assert len(snapshots) == 1
    assert snapshots[0].final_action == "skip"
    assert snapshots[0].skip_reason == "low_confidence:55"
    assert snapshots[0].technical is not None
    assert snapshots[0].sentiment is not None
    assert snapshots[0].ai_confidence == 55


@pytest.mark.asyncio
async def test_pipeline_risk_circuit_skips_records_risk(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet())
    monkeypatch.setattr(
        "main.check_risk",
        Mock(
            return_value=RiskCheckResult(
                passed=False,
                size_multiplier=0.0,
                reasons=["daily_loss_circuit"],
            )
        ),
    )

    await process_event(build_event(tx_hash="tx-risk"), build_portfolio(), -0.06, deps)

    snapshots = trades_repo.get_snapshots(limit=10)
    assert len(snapshots) == 1
    assert snapshots[0].final_action == "skip"
    assert snapshots[0].risk is not None
    assert snapshots[0].risk.passed is False
    assert snapshots[0].cost is None


@pytest.mark.asyncio
async def test_pipeline_cost_too_high_skips_records_cost(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet())
    monkeypatch.setattr("main.estimate_cost", Mock(return_value=build_cost(total_cost_pct=0.02)))
    monkeypatch.setattr("main.should_reject", Mock(return_value=True))

    await process_event(build_event(tx_hash="tx-cost"), build_portfolio(), 0.0, deps)

    snapshots = trades_repo.get_snapshots(limit=10)
    assert len(snapshots) == 1
    assert snapshots[0].final_action == "skip"
    assert snapshots[0].skip_reason == "cost_too_high"
    assert snapshots[0].cost is not None


@pytest.mark.asyncio
async def test_pipeline_full_run_records_history(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet(address="0xknown"))

    def quant_filter_side_effect(event, wallet, binance_symbols, min_trade_usd, recent_events, dedup_window_seconds=600):
        if event.tx_hash.startswith("quant"):
            return False, "below_min_trade_usd"
        return True, "ok"

    async def ai_side_effect(*, event, **kwargs):
        if event.tx_hash.startswith("ai"):
            return build_ai_score(confidence=55)
        return build_ai_score()

    def risk_side_effect(*, new_symbol, **kwargs):
        if kwargs["daily_pnl_pct"] <= -0.06 or new_symbol == "RISK/USDT":
            return RiskCheckResult(passed=False, size_multiplier=0.0, reasons=["daily_loss_circuit"])
        return RiskCheckResult(passed=True, size_multiplier=1.0, reasons=[])

    def cost_side_effect(*, symbol, **kwargs):
        if symbol == "COST/USDT":
            return build_cost(total_cost_pct=0.02)
        return build_cost()

    def should_reject_side_effect(estimate):
        return estimate.total_cost_pct >= 0.02

    monkeypatch.setattr("main.quant_filter", Mock(side_effect=quant_filter_side_effect))
    monkeypatch.setattr("main.score_signal", AsyncMock(side_effect=ai_side_effect))
    monkeypatch.setattr("main.check_risk", Mock(side_effect=risk_side_effect))
    monkeypatch.setattr("main.estimate_cost", Mock(side_effect=cost_side_effect))
    monkeypatch.setattr("main.should_reject", Mock(side_effect=should_reject_side_effect))

    events: list[tuple[OnChainEvent, float]] = []
    for index in range(6):
        events.append((build_event(wallet="0xmissing", tx_hash=f"unknown-{index}"), 0.0))
        events.append((build_event(wallet="0xknown", tx_hash=f"quant-{index}", amount_usd="500"), 0.0))
        events.append((build_event(wallet="0xknown", tx_hash=f"ai-{index}"), 0.0))
        risk_event = build_event(wallet="0xknown", tx_hash=f"risk-{index}")
        risk_event = OnChainEvent(**{**risk_event.__dict__, "token_symbol": "RISK"})
        events.append((risk_event, -0.06))

    for index in range(4):
        cost_event = build_event(wallet="0xknown", tx_hash=f"cost-{index}")
        cost_event = OnChainEvent(**{**cost_event.__dict__, "token_symbol": "COST"})
        events.append((cost_event, 0.0))

    for index in range(2):
        events.append((build_event(wallet="0xknown", tx_hash=f"success-{index}"), 0.0))

    for event, daily_pnl in events:
        await process_event(event, build_portfolio(), daily_pnl, deps)

    trades = trades_repo.recent_trades(hours=24)
    snapshots = trades_repo.get_snapshots(limit=100)
    assert len(events) == 30
    assert len(trades) == 2
    assert len(snapshots) == 30


@pytest.mark.asyncio
async def test_pipeline_slippage_fields_persisted(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps, trades_repo = build_deps(tmp_path, monkeypatch)
    deps.addresses_repo.upsert_wallet(build_wallet())

    await process_event(build_event(tx_hash="tx-slippage"), build_portfolio(), 0.0, deps)

    trade = trades_repo.recent_trades(hours=24)[0]
    assert trade["pre_trade_mid_price"] is not None
    assert trade["estimated_slippage_pct"] is not None
    assert trade["realized_slippage_pct"] is not None
    assert trade["realized_fee_pct"] is not None
