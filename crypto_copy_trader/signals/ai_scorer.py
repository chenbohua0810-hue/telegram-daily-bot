from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from signals.llm_backend import LLMBackendError

if TYPE_CHECKING:
    from signals.llm_backend import LLMBackend


PROMPT_SYSTEM = (
    "你是加密貨幣跟單系統的信號仲裁者。基於以下結構化資料，判斷此筆鏈上事件是否值得執行跟單。"
    "輸出嚴格 JSON（schema 在 user message 最後）。"
)

PROMPT_USER_TEMPLATE = """鏈上事件：
  錢包：{wallet_address} (chain={chain}, trust={trust_level})
  幣種：{token_symbol}
  金額：${amount_usd:,.0f}
  類型：{tx_type}

錢包資料：
  勝率：{win_rate:.1%}（近 30 天 {recent_win_rate:.1%}）
  交易筆數：{trade_count}
  最大回撤：{max_drawdown:.1%}
  資金規模：${funds_usd:,.0f}

技術信號：
  趨勢：{trend}
  動量：{momentum}
  波動率：{volatility}
  統計：{stat_arb}
  信心：{technical_confidence:.2f}

情緒信號：
  訊號：{sentiment_signal}
  分數：{sentiment_score:.2f}（樣本 {source_count}）

請綜合以上資訊輸出 JSON（且只有 JSON，不要任何 markdown 或前後文）：
{{"confidence_score": <0–100 整數>, "reasoning": "<一句話，繁體中文，≤ 80 字>", "recommendation": "execute" | "skip"}}
"""


class AIScorerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIScore:
    confidence_score: int
    reasoning: str
    recommendation: Literal["execute", "skip"]

    @property
    def confidence(self) -> int:
        return self.confidence_score


async def score_signal(
    *,
    event,
    wallet,
    technical,
    sentiment,
    backend: "LLMBackend",
) -> AIScore:
    prompt = PROMPT_USER_TEMPLATE.format(
        wallet_address=wallet.address,
        chain=wallet.chain,
        trust_level=wallet.trust_level,
        token_symbol=event.token_symbol,
        amount_usd=float(event.amount_usd),
        tx_type=event.tx_type,
        win_rate=wallet.win_rate,
        recent_win_rate=wallet.recent_win_rate,
        trade_count=wallet.trade_count,
        max_drawdown=wallet.max_drawdown,
        funds_usd=wallet.funds_usd,
        trend=technical.trend,
        momentum=technical.momentum,
        volatility=technical.volatility,
        stat_arb=technical.stat_arb,
        technical_confidence=technical.confidence,
        sentiment_signal=sentiment.signal,
        sentiment_score=sentiment.score,
        source_count=sentiment.source_count,
    )

    try:
        payload = await backend.score_one(prompt, max_tokens=300)
        return AIScore(
            confidence_score=int(payload["confidence_score"]),
            reasoning=str(payload["reasoning"]),
            recommendation=payload["recommendation"],
        )
    except LLMBackendError as exc:
        raise AIScorerError("Failed to score signal") from exc
