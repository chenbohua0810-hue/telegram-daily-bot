from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import anthropic
import ccxt.async_support as ccxt
import httpx

from analysis.performance_tracker import PerformanceTracker
from analysis.telegram_notifier import TelegramNotifier
from analysis.trade_logger import TradeLogger
from config import get_settings
from execution.binance_executor import BinanceExecutor
from execution.position_sizer import compute_position_size
from execution.risk_guard import check_risk
from models.decision import TradeDecision
from models.events import OnChainEvent
from models.snapshot import DecisionSnapshot
from monitors.bsc_monitor import BscMonitor
from monitors.eth_monitor import EthMonitor
from monitors.sol_monitor import SolMonitor
from signals.ai_scorer import AIScorerError, score_signal
from signals.quant_filter import quant_filter
from signals.sentiment import compute_sentiment
from signals.slippage_fee import estimate_cost, should_reject
from signals.technicals import compute_technicals, ohlcv_to_volatility
from storage.addresses_repo import AddressesRepo
from storage.db import init_addresses_db, init_trades_db
from storage.event_log import EventLog
from storage.trades_repo import TradesRepo
from wallet_scorer.scorer import WalletScorer


CorrelationProvider = Callable[[str, list[str]], dict[str, float]]


@dataclass(frozen=True)
class PipelineDeps:
    settings: Any
    addresses_repo: AddressesRepo
    trades_repo: TradesRepo
    executor: Any
    anthropic: Any
    notifier: Any
    trade_logger: TradeLogger
    http: Any
    binance_symbols: set[str]
    recent_events_cache: list[OnChainEvent]
    btc_24h_vol_pct: float
    correlation_provider: CorrelationProvider


@dataclass(frozen=True)
class Runtime:
    deps: PipelineDeps
    tracker: PerformanceTracker
    wallet_scorer: WalletScorer
    monitors: list[Any]


async def process_event(
    event: OnChainEvent,
    portfolio,
    daily_pnl: float,
    deps: PipelineDeps,
) -> None:
    symbol = f"{event.token_symbol}/USDT"
    builder = _new_snapshot_builder(event, symbol)

    try:
        btc_price = float(await deps.executor.fetch_price("BTC/USDT"))
        builder.with_market_regime(btc_price=btc_price, btc_vol_pct=deps.btc_24h_vol_pct)

        wallet = deps.addresses_repo.get_wallet(event.wallet)
        if wallet is None:
            return _log_skip(event, "unknown_wallet", builder, deps)

        passed, reason = quant_filter(
            event,
            wallet,
            deps.binance_symbols,
            deps.settings.MIN_TRADE_USD,
            recent_events=deps.recent_events_cache,
        )
        if not passed:
            return _log_skip(event, reason, builder, deps)

        ohlcv = await deps.executor.fetch_ohlcv(symbol, "1h", 200)
        technical_signal, technical_indicators = compute_technicals(ohlcv)
        builder.with_technical(technical_signal, technical_indicators)

        sentiment_signal, sentiment_counts = await compute_sentiment(
            event.token_symbol,
            deps.http,
            deps.settings.CRYPTOPANIC_API_KEY,
        )
        builder.with_sentiment(sentiment_signal, sentiment_counts)

        try:
            ai = await score_signal(
                event=event,
                wallet=wallet,
                technical=technical_signal,
                sentiment=sentiment_signal,
                anthropic_client=deps.anthropic,
                model=deps.settings.AI_SCORER_MODEL,
            )
        except AIScorerError:
            return _log_skip(event, "ai_scorer_error", builder, deps)

        builder.with_ai(ai)
        if (
            ai.confidence_score < deps.settings.AI_SCORER_CONFIDENCE_THRESHOLD
            or ai.recommendation == "skip"
        ):
            return _log_skip(event, f"low_confidence:{ai.confidence_score}", builder, deps)

        base_size = compute_position_size(
            portfolio=portfolio,
            asset_volatility=ohlcv_to_volatility(technical_indicators),
            max_position_pct=deps.settings.MAX_POSITION_PCT,
        )
        risk = check_risk(
            new_symbol=symbol,
            new_size_usdt=base_size,
            portfolio=portfolio,
            correlation_provider=deps.correlation_provider,
            daily_pnl_pct=daily_pnl,
            max_concurrent=deps.settings.MAX_CONCURRENT_POSITIONS,
            daily_loss_circuit=deps.settings.DAILY_LOSS_CIRCUIT,
        )
        builder.with_risk(risk)
        if not risk.passed:
            reasons = ",".join(risk.reasons)
            return _log_skip(event, f"risk_blocked:{reasons}", builder, deps)

        final_size = base_size * Decimal(str(getattr(risk, "size_multiplier", 1.0)))
        orderbook = await deps.executor.fetch_orderbook(symbol)
        cost = estimate_cost(
            order_usdt=float(final_size),
            symbol=symbol,
            orderbook_fetcher=lambda _symbol: orderbook,
            technical_confidence=technical_signal.confidence,
        )
        builder.with_cost(cost)
        if should_reject(cost):
            return _log_skip(event, "cost_too_high", builder, deps)

        decision = TradeDecision(
            action="buy" if event.tx_type == "swap_in" else "sell",
            symbol=symbol,
            quantity_usdt=float(final_size),
            confidence=ai.confidence_score,
            reasoning=ai.reasoning,
            source_wallet=event.wallet,
        )
        snapshot = builder.execute(decision.action)
        result = await deps.executor.execute(
            decision,
            estimated_slippage_pct=cost.slippage_pct,
            estimated_fee_pct=cost.fee_pct,
        )
        deps.trade_logger.log_fill(decision, result, snapshot)
        await deps.notifier.notify_trade_fill(decision, result)
    finally:
        _append_recent_event(deps.recent_events_cache, event)


async def process_events(
    events: list[OnChainEvent],
    portfolio,
    daily_pnl: float,
    deps: PipelineDeps,
) -> None:
    for event in events:
        await process_event(event, portfolio, daily_pnl, deps)


async def wallet_scorer_loop(wallet_scorer: WalletScorer) -> None:
    while True:
        await wallet_scorer.evaluate_all()
        await asyncio.sleep(7 * 24 * 60 * 60)


async def daily_summary_loop(tracker: PerformanceTracker, trades_repo: TradesRepo, notifier: Any) -> None:
    while True:
        await asyncio.sleep(_seconds_until_next_utc_midnight())
        trades = trades_repo.recent_trades(hours=24)
        win_trades = [
            trade for trade in trades if float(trade.get("price") or 0) > float(trade.get("pre_trade_mid_price") or 0)
        ]
        win_rate = 0.0 if not trades else len(win_trades) / len(trades)
        today = datetime.now(timezone.utc).date().isoformat()
        await notifier.notify_daily_summary(
            today,
            total_trades=len(trades),
            win_rate=win_rate,
            pnl_pct=tracker.daily_pnl_pct(today),
        )


async def build_runtime() -> Runtime:
    settings = get_settings()
    _ensure_parent_dirs(settings)
    init_addresses_db(settings.ADDRESSES_DB_PATH)
    init_trades_db(settings.TRADES_DB_PATH)

    addresses_repo = AddressesRepo(settings.ADDRESSES_DB_PATH)
    trades_repo = TradesRepo(settings.TRADES_DB_PATH)
    event_log = EventLog(settings.EVENTS_LOG_PATH)

    exchange = ccxt.binance(
        {
            "apiKey": settings.BINANCE_API_KEY,
            "secret": settings.BINANCE_API_SECRET,
            "enableRateLimit": True,
        }
    )
    executor = BinanceExecutor(
        api_key=settings.BINANCE_API_KEY,
        api_secret=settings.BINANCE_API_SECRET,
        paper_trading=settings.PAPER_TRADING,
        exchange=exchange,
        trades_repo=trades_repo,
        record_trades=False,
    )
    binance_symbols = await executor.load_markets()

    notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
    tracker = PerformanceTracker(trades_repo)
    trade_logger = TradeLogger(trades_repo)
    anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    wallet_scorer = WalletScorer(
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        anthropic_client=anthropic_client,
        model=settings.AI_SCORER_MODEL,
    )

    btc_24h_vol_pct = await _fetch_btc_24h_volatility(executor)
    shared_http = httpx.AsyncClient(timeout=10)
    deps = PipelineDeps(
        settings=settings,
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        executor=executor,
        anthropic=anthropic_client,
        notifier=notifier,
        trade_logger=trade_logger,
        http=shared_http,
        binance_symbols=binance_symbols,
        recent_events_cache=[],
        btc_24h_vol_pct=btc_24h_vol_pct,
        correlation_provider=lambda new_symbol, existing_symbols: {},
    )
    monitors = [
        EthMonitor(
            settings.ETHERSCAN_API_KEY,
            addresses_repo,
            event_log,
            price_fetcher=executor.fetch_price,
            binance_symbols=binance_symbols,
            client=shared_http,
        ),
        SolMonitor(
            settings.SOLSCAN_API_KEY,
            addresses_repo,
            event_log,
            price_fetcher=executor.fetch_price,
            binance_symbols=binance_symbols,
            client=shared_http,
        ),
        BscMonitor(
            settings.BSCSCAN_API_KEY,
            addresses_repo,
            event_log,
            price_fetcher=executor.fetch_price,
            binance_symbols=binance_symbols,
            client=shared_http,
        ),
    ]
    return Runtime(deps=deps, tracker=tracker, wallet_scorer=wallet_scorer, monitors=monitors)


async def main() -> None:
    runtime = await build_runtime()
    await runtime.deps.notifier.notify_risk_alert("crypto copy trader started")

    asyncio.create_task(wallet_scorer_loop(runtime.wallet_scorer))
    asyncio.create_task(daily_summary_loop(runtime.tracker, runtime.deps.trades_repo, runtime.deps.notifier))

    try:
        while True:
            events: list[OnChainEvent] = []
            for monitor in runtime.monitors:
                events.extend(await monitor.poll_once())

            portfolio = await runtime.deps.executor.fetch_portfolio()
            daily_pnl = runtime.tracker.daily_pnl_pct()
            runtime = Runtime(
                deps=PipelineDeps(
                    **{**runtime.deps.__dict__, "btc_24h_vol_pct": await _fetch_btc_24h_volatility(runtime.deps.executor)}
                ),
                tracker=runtime.tracker,
                wallet_scorer=runtime.wallet_scorer,
                monitors=runtime.monitors,
            )
            await process_events(events, portfolio, daily_pnl, runtime.deps)
            runtime.tracker.update_daily_pnl(portfolio.total_value_usdt)
            await asyncio.sleep(runtime.deps.settings.POLL_INTERVAL_SECONDS)
    finally:
        await runtime.deps.http.aclose()
        await runtime.deps.executor.exchange.close()


def _new_snapshot_builder(event: OnChainEvent, symbol: str):
    from models.snapshot import DecisionSnapshotBuilder

    return DecisionSnapshotBuilder(
        event=event,
        symbol=symbol,
        recorded_at=datetime.now(timezone.utc),
    )


def _log_skip(event: OnChainEvent, reason: str, builder: Any, deps: PipelineDeps) -> None:
    snapshot: DecisionSnapshot = builder.skip(reason)
    deps.trade_logger.log_skip(event, reason, snapshot)


def _append_recent_event(recent_events: list[OnChainEvent], event: OnChainEvent) -> None:
    recent_events.append(event)
    if len(recent_events) > 500:
        del recent_events[:-500]


async def _fetch_btc_24h_volatility(executor: Any) -> float:
    ohlcv = await executor.fetch_ohlcv("BTC/USDT", "1h", 200)
    _, indicators = compute_technicals(ohlcv)
    return ohlcv_to_volatility(indicators)


def _ensure_parent_dirs(settings: Any) -> None:
    for path in (
        settings.ADDRESSES_DB_PATH,
        settings.TRADES_DB_PATH,
        settings.EVENTS_LOG_PATH,
    ):
        Path(path).parent.mkdir(parents=True, exist_ok=True)


def _seconds_until_next_utc_midnight() -> float:
    now = datetime.now(timezone.utc)
    next_midnight = datetime.combine(
        now.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return max((next_midnight - now).total_seconds(), 1.0)


if __name__ == "__main__":
    asyncio.run(main())
