from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from main import PipelineDeps, process_event
from models import OnChainEvent
from models import Portfolio, Position
from models import SentimentCounts, SentimentSignal, TechnicalIndicators, TechnicalSignal, WalletScore
from signals.scorer import AIScore
from signals.router import LLMBackendError
from signals.router import PriorityDecision
from storage import AddressesRepo
from storage import TradesRepo


def build_wallet() -> WalletScore:
    return WalletScore(
        address="0xabc123",
        chain="eth",
        win_rate=0.68,
        trade_count=80,
        max_drawdown=0.18,
        funds_usd=150000.0,
        recent_win_rate=0.71,
        trust_level="high",
        status="active",
    )


def build_event(*, tx_hash: str = "tx-happy", amount_usd: str = "15000") -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash=tx_hash,
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("5"),
        amount_usd=Decimal(amount_usd),
        raw={"block_number": 100},
        token_address="",
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


class FakeExecutor:
    def __init__(self) -> None:
        self.fetch_price = AsyncMock(return_value=Decimal("62000"))
        self.fetch_ohlcv = AsyncMock(return_value=pd.DataFrame({"close": [1]}))
        self.fetch_orderbook = AsyncMock(return_value={"bids": [[2498, 5]], "asks": [[2500, 5]]})
        self.execute = AsyncMock()


def build_deps(tmp_path) -> PipelineDeps:
    addresses_repo = AddressesRepo(str(tmp_path / "addresses.db"))
    trades_repo = TradesRepo(str(tmp_path / "trades.db"))
    addresses_repo.upsert_wallet(build_wallet())
    return PipelineDeps(
        settings=SimpleNamespace(
            MIN_TRADE_USD=10000.0,
            MAX_POSITION_PCT=0.10,
            DAILY_LOSS_CIRCUIT=-0.05,
            MAX_CONCURRENT_POSITIONS=10,
            AI_SCORER_CONFIDENCE_THRESHOLD=60,
            AI_SCORER_MODEL="claude-haiku-4-5-20251001",
            CRYPTOPANIC_API_KEY="***",
            HIGH_VALUE_USD_THRESHOLD=50000.0,
            P1_HIGH_TRUST_MIN_USD=20000.0,
            P1_HIGH_TRUST_RECENT_WINRATE=0.60,
        ),
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        executor=FakeExecutor(),
        anthropic=SimpleNamespace(),
        claude_backend=SimpleNamespace(score_one=AsyncMock(return_value={"confidence_score": 95, "reasoning": "p0", "recommendation": "execute"})),
        batch_scorer=SimpleNamespace(submit=AsyncMock(return_value=AIScore(confidence_score=77, reasoning="batch", recommendation="execute"))),
        notifier=SimpleNamespace(
            notify_trade_fill=AsyncMock(),
            notify_trade_skip=AsyncMock(),
            notify_daily_summary=AsyncMock(),
            notify_risk_alert=AsyncMock(),
        ),
        trade_logger=SimpleNamespace(log_fill=Mock(), log_skip=Mock()),
        http=SimpleNamespace(),
        binance_symbols={"ETH/USDT", "BTC/USDT"},
        recent_events_cache=[],
        btc_24h_vol_pct=0.031,
        correlation_provider=lambda new_symbol, existing_symbols: {},
    )


@pytest.mark.asyncio
async def test_p0_skips_llm_call(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = build_deps(tmp_path)
    technicals = Mock(return_value=build_technicals())
    sentiment = AsyncMock(return_value=build_sentiment())
    score_signal = AsyncMock(return_value=AIScore(confidence_score=91, reasoning="p0", recommendation="execute"))

    monkeypatch.setattr("main.compute_technicals", technicals)
    monkeypatch.setattr("main.compute_sentiment", sentiment)
    monkeypatch.setattr("main.quant_filter", Mock(return_value=(True, "ok")))
    monkeypatch.setattr("main.assign_priority", Mock(return_value=PriorityDecision(level="P0", reason="high_value_usd")))
    monkeypatch.setattr("main.score_signal", score_signal)
    monkeypatch.setattr("main.compute_position_size", Mock(side_effect=AssertionError("stop after routing")))

    with pytest.raises(AssertionError, match="stop after routing"):
        await process_event(build_event(amount_usd="60000"), build_portfolio(), 0.0, deps)

    technicals.assert_called_once()
    sentiment.assert_awaited_once()
    score_signal.assert_not_awaited()
    deps.claude_backend.score_one.assert_not_awaited()
    deps.batch_scorer.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_p1_event_short_circuits_without_backend_calls(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = build_deps(tmp_path)
    technicals = Mock(return_value=build_technicals())
    sentiment = AsyncMock(return_value=build_sentiment())
    score_signal = AsyncMock()

    monkeypatch.setattr("main.compute_technicals", technicals)
    monkeypatch.setattr("main.compute_sentiment", sentiment)
    monkeypatch.setattr("main.quant_filter", Mock(return_value=(True, "ok")))
    monkeypatch.setattr("main.assign_priority", Mock(return_value=PriorityDecision(level="P1", reason="high_trust_direct_copy")))
    monkeypatch.setattr("main.score_signal", score_signal)
    monkeypatch.setattr("main.compute_position_size", Mock(side_effect=AssertionError("stop after routing")))

    with pytest.raises(AssertionError, match="stop after routing"):
        await process_event(build_event(amount_usd="25000"), build_portfolio(), 0.0, deps)

    technicals.assert_called_once()
    sentiment.assert_awaited_once()
    score_signal.assert_not_awaited()
    deps.claude_backend.score_one.assert_not_awaited()
    deps.batch_scorer.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_p2_event_uses_batch_scorer(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = build_deps(tmp_path)
    technicals = Mock(return_value=build_technicals())
    sentiment = AsyncMock(return_value=build_sentiment())
    score_signal = AsyncMock()

    monkeypatch.setattr("main.compute_technicals", technicals)
    monkeypatch.setattr("main.compute_sentiment", sentiment)
    monkeypatch.setattr("main.quant_filter", Mock(return_value=(True, "ok")))
    monkeypatch.setattr("main.assign_priority", Mock(return_value=PriorityDecision(level="P2", reason="batch_scorer")))
    monkeypatch.setattr("main.score_signal", score_signal)
    monkeypatch.setattr("main.compute_position_size", Mock(side_effect=AssertionError("stop after routing")))

    with pytest.raises(AssertionError, match="stop after routing"):
        await process_event(build_event(amount_usd="15000"), build_portfolio(), 0.0, deps)

    deps.batch_scorer.submit.assert_awaited_once()
    score_signal.assert_not_awaited()
    deps.claude_backend.score_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_position_skips_new_signal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = build_deps(tmp_path)
    existing_position = Position(
        symbol="ETH/USDT",
        quantity=Decimal("1"),
        avg_entry_price=Decimal("2500"),
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        source_wallet="0xabc123",
    )
    portfolio = Portfolio(
        cash_usdt=Decimal("50000"),
        positions={"ETH/USDT": existing_position},
        total_value_usdt=Decimal("100000"),
        daily_pnl_pct=0.0,
    )
    monkeypatch.setattr("main.compute_technicals", Mock(return_value=build_technicals()))
    monkeypatch.setattr("main.compute_sentiment", AsyncMock(return_value=build_sentiment()))
    monkeypatch.setattr("main.quant_filter", Mock(return_value=(True, "ok")))
    monkeypatch.setattr("main.assign_priority", Mock(return_value=PriorityDecision(level="P0", reason="high_value_usd")))

    await process_event(build_event(amount_usd="60000"), portfolio, 0.0, deps)

    deps.trade_logger.log_skip.assert_called_once()
    assert deps.trade_logger.log_skip.call_args.args[1] == "existing_position"
    deps.executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_p3_event_logs_skip_without_touching_any_backend(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = build_deps(tmp_path)
    log_skip = Mock()
    score_signal = AsyncMock()

    monkeypatch.setattr("main.quant_filter", Mock(return_value=(True, "ok")))
    monkeypatch.setattr("main.assign_priority", Mock(return_value=PriorityDecision(level="P3", reason="quant_filter_failed")))
    monkeypatch.setattr("main._log_skip", log_skip)
    monkeypatch.setattr("main.score_signal", score_signal)

    await process_event(build_event(amount_usd="15000"), build_portfolio(), 0.0, deps)

    log_skip.assert_called_once()
    assert log_skip.call_args.args[1] == "p3:quant_filter_failed"
    score_signal.assert_not_awaited()
    deps.batch_scorer.submit.assert_not_awaited()
    deps.claude_backend.score_one.assert_not_awaited()
