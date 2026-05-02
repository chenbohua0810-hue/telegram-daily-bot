from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import anthropic
import ccxt.async_support as ccxt
import httpx
from telegram import Bot

from config import get_settings
from execution import BinanceExecutor, compute_position_size, check_risk
from models import DecisionSnapshot, OnChainEvent, TradeDecision
from monitors import BirdeyeSolMonitor, BscMonitor, BscWebSocketMonitor, EthMonitor, EthWebSocketMonitor, SolMonitor, SolWebSocketMonitor
from reporting import PerformanceTracker, TelegramNotifier, TradeLogger
from signals.exit_router import should_mirror_exit
from signals.filters import compute_sentiment, compute_technicals, estimate_cost, ohlcv_to_volatility, quant_filter, should_reject
from signals.router import AnthropicBackend, FallbackBackend, LLMBackendError, OpenAICompatBackend, assign_priority
from signals.scorer import AIScore, AIScorerError, BatchScorer, PROMPT_SYSTEM, score_signal
from signals.symbol_mapper import map_to_binance
from storage import AddressesRepo, EventLog, TradesRepo, init_addresses_db, init_trades_db
from wallet_scorer import WalletScorer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


CorrelationProvider = Callable[[str, list[str]], dict[str, float]]
_SYMBOL_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class PipelineDeps:
    settings: Any
    addresses_repo: AddressesRepo
    trades_repo: TradesRepo
    executor: Any
    anthropic: Any
    claude_backend: Any
    batch_scorer: Any
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
    if event.tx_type == "swap_out":
        await _process_exit_event(event, portfolio, deps)
        _append_recent_event(deps.recent_events_cache, event)
        return

    symbol = map_to_binance(event.chain, event.token_address, event.token_symbol) or f"{event.token_symbol}/USDT"
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

        known_tokens = deps.trades_repo.get_traded_symbols()
        priority = assign_priority(
            event,
            wallet,
            known_tokens=known_tokens,
            quant_passed=passed,
            high_value_usd=deps.settings.HIGH_VALUE_USD_THRESHOLD,
            p1_min_usd=deps.settings.P1_HIGH_TRUST_MIN_USD,
            p1_min_win_rate=deps.settings.P1_HIGH_TRUST_RECENT_WINRATE,
        )
        if priority.level == "P3":
            return _log_skip(event, f"p3:{priority.reason}", builder, deps)

        ohlcv = await deps.executor.fetch_ohlcv(symbol, "1h", 200)
        technical_signal, technical_indicators = compute_technicals(ohlcv)
        builder.with_technical(technical_signal, technical_indicators)

        sentiment_signal, sentiment_counts = await compute_sentiment(
            event.token_symbol,
            deps.http,
            deps.settings.CRYPTOPANIC_API_KEY,
        )
        builder.with_sentiment(sentiment_signal, sentiment_counts)

        if priority.level == "P1":
            ai = AIScore(
                confidence_score=100,
                reasoning="P1_direct_copy_trade",
                recommendation="execute",
            )
        elif priority.level == "P0":
            try:
                ai = await score_signal(
                    event=event,
                    wallet=wallet,
                    technical=technical_signal,
                    sentiment=sentiment_signal,
                    backend=deps.claude_backend,
                )
            except AIScorerError:
                return _log_skip(event, "ai_scorer_error", builder, deps)
        else:
            try:
                batch_result = await deps.batch_scorer.submit(
                    event=event,
                    wallet=wallet,
                    technical=technical_signal,
                    sentiment=sentiment_signal,
                )
                ai = await batch_result if isinstance(batch_result, asyncio.Future) else batch_result
            except LLMBackendError:
                return _log_skip(event, "llm_backend_exhausted", builder, deps)

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
        async with _get_symbol_lock(symbol):
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


async def _process_exit_event(event: OnChainEvent, portfolio: Any, deps: PipelineDeps) -> None:
    symbol = map_to_binance(event.chain, event.token_address, event.token_symbol)
    builder = _new_snapshot_builder(event, symbol or f"{event.token_symbol}/USDT")
    if symbol is None:
        _log_skip(event, "exit:not_on_binance", builder, deps)
        return

    async with _get_symbol_lock(symbol):
        current_position = _find_current_position(deps.trades_repo, symbol)
        if current_position is None and hasattr(deps.trades_repo, "get_positions"):
            _log_skip(event, "exit:no_matching_position", builder, deps)
            return
        if current_position is None:
            current_position = portfolio.positions.get(symbol)
        if current_position is None:
            _log_skip(event, "exit:no_matching_position", builder, deps)
            return
        exit_event = _with_rolling_sell_fraction(event, deps.recent_events_cache)
        decision = should_mirror_exit(exit_event, current_position)
        if not decision.should_exit or decision.symbol is None:
            _log_skip(event, f"exit:{decision.reason}", builder, deps)
            return

        result = await deps.executor.execute_exit(
            decision.symbol,
            decision.fraction,
            position=current_position,
            source_wallet=event.wallet,
            reason=decision.reason,
        )

    exit_trade = TradeDecision(
        action="sell",
        symbol=decision.symbol,
        quantity_usdt=float(current_position.quantity * current_position.avg_entry_price * decision.fraction),
        confidence=100,
        reasoning=decision.reason,
        source_wallet=event.wallet,
    )
    snapshot = builder.execute("sell")
    deps.trade_logger.log_fill(exit_trade, result, snapshot)
    notifier = getattr(deps.notifier, "notify_risk_alert", None)
    if notifier is not None and result.success:
        await notifier(f"[EXIT] symbol={decision.symbol} fraction={decision.fraction} reason={decision.reason}")
    elif notifier is not None:
        await notifier(f"[EXIT_FAILED] symbol={decision.symbol} fraction={decision.fraction} reason={decision.reason} error={result.error}")


def _get_symbol_lock(symbol: str) -> asyncio.Lock:
    lock = _SYMBOL_LOCKS.get(symbol)
    if lock is not None:
        return lock

    new_lock = asyncio.Lock()
    _SYMBOL_LOCKS[symbol] = new_lock
    return new_lock


def _find_current_position(trades_repo: Any, symbol: str) -> Any | None:
    get_positions = getattr(trades_repo, "get_positions", None)
    if get_positions is None:
        return None

    positions = get_positions()
    for position in positions:
        if position.symbol == symbol:
            return position
    return None


def _with_rolling_sell_fraction(event: OnChainEvent, recent_events: list[OnChainEvent]) -> OnChainEvent:
    balance_before = event.raw.get("wallet_token_balance_before")
    if balance_before is None:
        return event

    symbol = map_to_binance(event.chain, event.token_address, event.token_symbol)
    cutoff = event.block_time - timedelta(minutes=30)
    rolling_amount = event.amount_token
    for recent_event in recent_events:
        recent_symbol = map_to_binance(
            recent_event.chain,
            recent_event.token_address,
            recent_event.token_symbol,
        )
        is_same_window = cutoff <= recent_event.block_time <= event.block_time
        is_same_exit = recent_event.tx_type == "swap_out" and recent_event.wallet == event.wallet
        if is_same_window and is_same_exit and recent_symbol == symbol:
            rolling_amount += recent_event.amount_token

    balance = Decimal(str(balance_before))
    if balance <= Decimal("0"):
        return event

    return replace(
        event,
        raw={**event.raw, "rolling_sold_fraction": str(rolling_amount / balance)},
    )


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

    notifier = TelegramNotifier(
        settings.TELEGRAM_BOT_TOKEN,
        settings.TELEGRAM_CHAT_ID,
        bot=Bot(token=settings.TELEGRAM_BOT_TOKEN),
    )
    await notifier.initialize()
    tracker = PerformanceTracker(trades_repo)
    trade_logger = TradeLogger(trades_repo)
    anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    claude_backend = AnthropicBackend(
        client=anthropic_client,
        model=settings.AI_SCORER_MODEL,
        system_prompt=PROMPT_SYSTEM,
    )
    wallet_scorer = WalletScorer(
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        anthropic_client=anthropic_client,
        model=settings.AI_SCORER_MODEL,
    )

    btc_24h_vol_pct = await _fetch_btc_24h_volatility(executor)
    shared_http = httpx.AsyncClient(timeout=10)
    primary_backend = OpenAICompatBackend(
        client=shared_http,
        base_url=settings.LLM_PRIMARY_BASE_URL,
        model=settings.LLM_PRIMARY_MODEL,
        api_key=settings.LLM_PRIMARY_API_KEY,
        name=settings.LLM_PRIMARY_NAME,
    )
    fallback_backends: list[Any] = [primary_backend]
    if settings.LLM_SECONDARY_BASE_URL:
        fallback_backends = [
            *fallback_backends,
            OpenAICompatBackend(
                client=shared_http,
                base_url=settings.LLM_SECONDARY_BASE_URL,
                model=settings.LLM_SECONDARY_MODEL or settings.LLM_PRIMARY_MODEL,
                api_key=settings.LLM_SECONDARY_API_KEY or settings.LLM_PRIMARY_API_KEY,
                name=settings.LLM_SECONDARY_NAME or "secondary",
            ),
        ]
    fallback_backends = [*fallback_backends, claude_backend]
    p2_backend = FallbackBackend(fallback_backends)
    batch_scorer = BatchScorer(
        backend=p2_backend,
        window_seconds=settings.BATCH_WINDOW_SECONDS,
        max_batch_size=settings.BATCH_MAX_SIZE,
    )
    deps = PipelineDeps(
        settings=settings,
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        executor=executor,
        anthropic=anthropic_client,
        claude_backend=claude_backend,
        batch_scorer=batch_scorer,
        notifier=notifier,
        trade_logger=trade_logger,
        http=shared_http,
        binance_symbols=binance_symbols,
        recent_events_cache=[],
        btc_24h_vol_pct=btc_24h_vol_pct,
        correlation_provider=lambda new_symbol, existing_symbols: {},
    )
    eth_rest = EthMonitor(
        settings.ETHERSCAN_API_KEY,
        addresses_repo,
        event_log,
        price_fetcher=executor.fetch_price,
        binance_symbols=binance_symbols,
        client=shared_http,
    )
    if settings.BIRDEYE_API_KEY:
        sol_rest = BirdeyeSolMonitor(
            settings.BIRDEYE_API_KEY,
            addresses_repo,
            event_log,
            price_fetcher=executor.fetch_price,
            binance_symbols=binance_symbols,
            client=shared_http,
        )
    else:
        sol_rest = None
        logger.warning("BIRDEYE_API_KEY not set — SOL monitoring disabled")
    bsc_rest = (
        BscMonitor(
            settings.BSCSCAN_API_KEY,
            addresses_repo,
            event_log,
            price_fetcher=executor.fetch_price,
            binance_symbols=binance_symbols,
            client=shared_http,
        )
        if settings.BSCSCAN_API_KEY
        else None
    )
    rest_monitors = [m for m in [eth_rest, sol_rest, bsc_rest] if m is not None]
    if settings.USE_WEBSOCKET:
        monitors: list = [
            EthWebSocketMonitor(
                rest_monitor=eth_rest,
                ws_url=settings.ETH_WSS_URL,
                heartbeat_timeout_seconds=settings.WS_HEARTBEAT_TIMEOUT_SECONDS,
                reconnect_backoff_cap_seconds=settings.WS_RECONNECT_BACKOFF_CAP_SECONDS,
            ),
        ]
        if sol_rest is not None:
            monitors.append(
                SolWebSocketMonitor(
                    rest_monitor=sol_rest,
                    ws_url=settings.SOL_WSS_URL,
                    heartbeat_timeout_seconds=settings.WS_HEARTBEAT_TIMEOUT_SECONDS,
                    reconnect_backoff_cap_seconds=settings.WS_RECONNECT_BACKOFF_CAP_SECONDS,
                )
            )
        if bsc_rest is not None:
            monitors.append(
                BscWebSocketMonitor(
                    rest_monitor=bsc_rest,
                    ws_url=settings.BSC_WSS_URL,
                    heartbeat_timeout_seconds=settings.WS_HEARTBEAT_TIMEOUT_SECONDS,
                    reconnect_backoff_cap_seconds=settings.WS_RECONNECT_BACKOFF_CAP_SECONDS,
                )
            )
    else:
        monitors = rest_monitors
    return Runtime(deps=deps, tracker=tracker, wallet_scorer=wallet_scorer, monitors=monitors)


async def main() -> None:
    runtime = await build_runtime()
    await runtime.deps.notifier.notify_risk_alert("crypto copy trader started")

    asyncio.create_task(wallet_scorer_loop(runtime.wallet_scorer))
    asyncio.create_task(daily_summary_loop(runtime.tracker, runtime.deps.trades_repo, runtime.deps.notifier))
    stream_iterators = [monitor.stream().__aiter__() for monitor in runtime.monitors] if runtime.deps.settings.USE_WEBSOCKET else []

    try:
        while True:
            if runtime.deps.settings.USE_WEBSOCKET:
                events = await _read_websocket_events_once(
                    stream_iterators,
                    timeout_seconds=runtime.deps.settings.POLL_INTERVAL_SECONDS,
                )
            else:
                events = []
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
            if not runtime.deps.settings.USE_WEBSOCKET:
                await asyncio.sleep(runtime.deps.settings.POLL_INTERVAL_SECONDS)
    finally:
        await runtime.deps.batch_scorer.flush()
        await runtime.deps.http.aclose()
        await runtime.deps.executor.exchange.close()
        notifier_close = getattr(runtime.deps.notifier, "aclose", None)
        if notifier_close is not None:
            await notifier_close()


async def _read_websocket_events_once(
    stream_iterators: list[Any],
    *,
    timeout_seconds: int,
) -> list[OnChainEvent]:
    events: list[OnChainEvent] = []
    for iterator in stream_iterators:
        try:
            event = await asyncio.wait_for(iterator.__anext__(), timeout=timeout_seconds)
        except (StopAsyncIteration, TimeoutError):
            continue
        events.append(event)
    return events


def _new_snapshot_builder(event: OnChainEvent, symbol: str):
    from models import DecisionSnapshotBuilder

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
