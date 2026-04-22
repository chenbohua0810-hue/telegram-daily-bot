from __future__ import annotations

import asyncio
from dataclasses import dataclass

from signals.ai_scorer import AIScore
from signals.llm_backend import LLMBackend, LLMBackendError


DEFAULT_BATCH_MAX_TOKENS = 1000
DEFAULT_BATCH_MAX_INPUT_TOKENS = 6000


@dataclass(frozen=True)
class PendingScore:
    event: object
    wallet: object
    technical: object
    sentiment: object
    future: asyncio.Future[AIScore]
    created_at_monotonic: float


class BatchScorer:
    def __init__(self, backend: LLMBackend, window_seconds: int = 5, max_batch_size: int = 5) -> None:
        self._backend = backend
        self._window_seconds = window_seconds
        self._max_batch_size = max_batch_size
        self._buffer: list[PendingScore] = []
        self._timer_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._flush_latency_ms_samples: list[float] = []

    @property
    def batch_flush_latency_ms(self) -> float:
        if not self._flush_latency_ms_samples:
            return 0.0
        return sum(self._flush_latency_ms_samples) / len(self._flush_latency_ms_samples)

    async def submit(self, *, event, wallet, technical, sentiment) -> asyncio.Future[AIScore]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AIScore] = loop.create_future()
        should_flush_now = False

        async with self._lock:
            pending = PendingScore(
                event=event,
                wallet=wallet,
                technical=technical,
                sentiment=sentiment,
                future=future,
                created_at_monotonic=loop.time(),
            )
            self._buffer = [*self._buffer, pending]
            should_flush_now = len(self._buffer) >= self._max_batch_size
            self._cancel_timer_locked()
            if should_flush_now:
                self._timer_task = asyncio.create_task(self._flush_and_swallow())
            else:
                self._timer_task = asyncio.create_task(self._flush_after_window())

        return future

    async def flush(self) -> None:
        async with self._lock:
            batch = self._buffer
            self._buffer = []
            self._cancel_timer_locked()
            self._timer_task = None

        if not batch:
            return

        loop = asyncio.get_running_loop()
        started_at_monotonic = min(pending.created_at_monotonic for pending in batch)

        try:
            await self._flush_pending(batch)
            self._flush_latency_ms_samples = [
                *self._flush_latency_ms_samples,
                (loop.time() - started_at_monotonic) * 1000,
            ]
        except Exception as exc:
            self._resolve_batch_error(batch, exc)
            raise

    async def _flush_after_window(self) -> None:
        try:
            await asyncio.sleep(self._window_seconds)
            await self._flush_and_swallow()
        except asyncio.CancelledError:
            raise

    async def _flush_and_swallow(self) -> None:
        try:
            await self.flush()
        except Exception:
            return

    async def _flush_pending(self, batch: list[PendingScore]) -> None:
        prompt = self._build_prompt(batch)
        if self._estimate_input_tokens(prompt) > DEFAULT_BATCH_MAX_INPUT_TOKENS and len(batch) > 1:
            midpoint = len(batch) // 2
            left_batch = batch[:midpoint]
            right_batch = batch[midpoint:]
            await self._flush_pending(left_batch)
            await self._flush_pending(right_batch)
            return

        response = await self._backend.score_batch([prompt], max_tokens=DEFAULT_BATCH_MAX_TOKENS)
        if len(response) != len(batch):
            raise LLMBackendError(
                f"Batch response length mismatch: expected {len(batch)}, got {len(response)}"
            )

        for pending, payload in zip(batch, response, strict=True):
            if pending.future.done():
                continue
            pending.future.set_result(
                AIScore(
                    confidence_score=int(payload["confidence_score"]),
                    reasoning=str(payload["reasoning"]),
                    recommendation=payload["recommendation"],
                )
            )

    def _build_prompt(self, batch: list[PendingScore]) -> str:
        header = f"以下共 {len(batch)} 筆鏈上事件，請「逐筆獨立」評估，不要讓事件之間互相影響。"
        event_sections = [self._format_event(index=index, pending=pending) for index, pending in enumerate(batch, start=1)]
        output_section = (
            f"輸出 JSON array（長度必須等於 {len(batch)}），每筆 reasoning ≤ 50 字：\n"
            '[{"index": 1, "confidence_score": <0-100>, "reasoning": "...", '
            '"recommendation": "execute"|"skip"}, ...]'
        )
        return "\n\n".join([header, *event_sections, output_section])

    @staticmethod
    def _format_event(*, index: int, pending: PendingScore) -> str:
        event = pending.event
        wallet = pending.wallet
        technical = pending.technical
        sentiment = pending.sentiment
        return (
            f"事件 {index}：\n"
            f"  錢包：{wallet.address} (chain={wallet.chain}, trust={wallet.trust_level})\n"
            f"  幣種：{event.token_symbol}\n"
            f"  金額：${float(event.amount_usd):,.0f}\n"
            f"  類型：{event.tx_type}\n\n"
            f"錢包資料：\n"
            f"  勝率：{wallet.win_rate:.1%}（近 30 天 {wallet.recent_win_rate:.1%}）\n"
            f"  交易筆數：{wallet.trade_count}\n"
            f"  最大回撤：{wallet.max_drawdown:.1%}\n"
            f"  資金規模：${wallet.funds_usd:,.0f}\n\n"
            f"技術信號：\n"
            f"  趨勢：{technical.trend}\n"
            f"  動量：{technical.momentum}\n"
            f"  波動率：{technical.volatility}\n"
            f"  統計：{technical.stat_arb}\n"
            f"  信心：{technical.confidence:.2f}\n\n"
            f"情緒信號：\n"
            f"  訊號：{sentiment.signal}\n"
            f"  分數：{sentiment.score:.2f}（樣本 {sentiment.source_count}）"
        )

    @staticmethod
    def _estimate_input_tokens(prompt: str) -> int:
        return len(prompt) // 4

    def _cancel_timer_locked(self) -> None:
        if self._timer_task is None:
            return
        self._timer_task.cancel()

    @staticmethod
    def _resolve_batch_error(batch: list[PendingScore], exc: Exception) -> None:
        for pending in batch:
            if pending.future.done():
                continue
            pending.future.set_exception(exc)
