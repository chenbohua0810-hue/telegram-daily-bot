from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Any

from models import WalletScore, WalletStatus, classify_trust_level
from reporting import PerformanceTracker
from storage import WalletDecision, get_connection


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是 crypto copy trader 的 wallet scorer。"
    "根據提供的評估資料與既定規則，"
    "用一句繁體中文說明為什麼這個地址應該 keep、watch 或 retire。"
)


@dataclass(frozen=True)
class EvaluationResult:
    address: str
    new_score: WalletScore
    decision: WalletDecision
    reasoning: str


class WalletScorer:
    def __init__(
        self,
        addresses_repo,
        trades_repo,
        anthropic_client: Any,
        model: str,
    ) -> None:
        self._addresses_repo = addresses_repo
        self._trades_repo = trades_repo
        self._anthropic_client = anthropic_client
        self._model = model

    async def evaluate_wallet(
        self,
        wallet: WalletScore,
        recent_performance: dict,
    ) -> EvaluationResult:
        recent_win_rate = self._bounded_ratio(
            recent_performance.get("win_rate", wallet.recent_win_rate)
        )
        max_drawdown = max(
            wallet.max_drawdown,
            self._bounded_ratio(recent_performance.get("max_drawdown", wallet.max_drawdown)),
        )
        current_funds_usd = self._non_negative_float(
            recent_performance.get("current_funds_usd", wallet.funds_usd)
        )
        consecutive_losses_value = recent_performance.get("consecutive_losses")
        if consecutive_losses_value is None:
            consecutive_losses_value = self._count_consecutive_losses(wallet.address)
        consecutive_losses = max(0, int(consecutive_losses_value))
        weekly_trades = max(
            0,
            int(recent_performance.get("weekly_trades", recent_performance.get("trades", 0))),
        )
        weekly_win_rate = self._bounded_ratio(
            recent_performance.get("weekly_win_rate", recent_win_rate)
        )
        mev_suspect_count = max(0, int(recent_performance.get("mev_suspect_count", 0)))
        binance_listable_pnl_180d = self._non_negative_float(
            recent_performance.get("binance_listable_pnl_180d", wallet.binance_listable_pnl_180d)
        )

        weighted_win_rate = round(((wallet.win_rate * 1.0) + (recent_win_rate * 2.0)) / 3.0, 4)
        trust_level = classify_trust_level(weighted_win_rate, wallet.trade_count, max_drawdown)
        decision: WalletDecision = "keep"
        status: WalletStatus = "active"
        warnings: list[str] = []

        if mev_suspect_count >= 3:
            decision = "retire"
            status = "retired"
            trust_level = "low"
        elif max_drawdown > 0.40 or current_funds_usd < wallet.funds_usd * 0.5:
            decision = "retire"
            status = "retired"
            trust_level = "low"
        elif consecutive_losses >= 3:
            decision = "watch"
            status = "watch"
            trust_level = "low"

        if weekly_trades >= 5 and weekly_win_rate < 0.40:
            warnings.append("單週勝率低於 40%")

        new_score = replace(
            wallet,
            win_rate=weighted_win_rate,
            recent_win_rate=recent_win_rate,
            max_drawdown=max_drawdown,
            funds_usd=current_funds_usd,
            trust_level=trust_level,
            status=status,
            binance_listable_pnl_180d=binance_listable_pnl_180d,
        )
        reasoning = await self._build_reasoning(
            wallet=wallet,
            new_score=new_score,
            decision=decision,
            consecutive_losses=consecutive_losses,
            weekly_win_rate=weekly_win_rate,
            weekly_trades=weekly_trades,
            warnings=warnings,
            mev_suspect_count=mev_suspect_count,
        )
        return EvaluationResult(
            address=wallet.address,
            new_score=new_score,
            decision=decision,
            reasoning=reasoning,
        )

    async def evaluate_all(self) -> list[EvaluationResult]:
        tracker = PerformanceTracker(self._trades_repo)
        results: list[EvaluationResult] = []

        for wallet in self._list_evaluable_wallets():
            weekly_metrics = self._weekly_metrics(wallet.address)
            recent_performance = {
                **tracker.wallet_performance(wallet.address),
                "consecutive_losses": self._count_consecutive_losses(wallet.address),
                **weekly_metrics,
            }
            result = await self.evaluate_wallet(wallet, recent_performance)
            self._addresses_repo.upsert_wallet(result.new_score)
            self._addresses_repo.append_history(
                result.address,
                result.new_score,
                result.decision,
                result.reasoning,
            )
            results.append(result)

        return results

    async def _build_reasoning(
        self,
        *,
        wallet: WalletScore,
        new_score: WalletScore,
        decision: WalletDecision,
        consecutive_losses: int,
        weekly_win_rate: float,
        weekly_trades: int,
        warnings: list[str],
        mev_suspect_count: int = 0,
    ) -> str:
        prompt_payload = {
            "address": wallet.address,
            "decision": decision,
            "old_score": {
                "win_rate": wallet.win_rate,
                "recent_win_rate": wallet.recent_win_rate,
                "max_drawdown": wallet.max_drawdown,
                "funds_usd": wallet.funds_usd,
                "trust_level": wallet.trust_level,
                "status": wallet.status,
                "binance_listable_pnl_180d": wallet.binance_listable_pnl_180d,
            },
            "new_score": {
                "win_rate": new_score.win_rate,
                "recent_win_rate": new_score.recent_win_rate,
                "max_drawdown": new_score.max_drawdown,
                "funds_usd": new_score.funds_usd,
                "trust_level": new_score.trust_level,
                "status": new_score.status,
                "binance_listable_pnl_180d": new_score.binance_listable_pnl_180d,
            },
            "rules": {
                "retire_on_max_drawdown_gt_40pct": True,
                "watch_on_3_consecutive_losses": True,
                "warn_on_weekly_win_rate_lt_40pct_with_5_trades": True,
                "retire_on_funds_drop_50pct": True,
                "retire_on_3_mev_suspicions": True,
            },
            "signals": {
                "consecutive_losses": consecutive_losses,
                "weekly_win_rate": weekly_win_rate,
                "weekly_trades": weekly_trades,
                "warnings": warnings,
                "mev_suspect_count": mev_suspect_count,
            },
        }

        try:
            response = await self._anthropic_client.messages.create(
                model=self._model,
                max_tokens=120,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(prompt_payload, ensure_ascii=False),
                    }
                ],
            )
            return self._extract_text(response) or f"自動規則：{decision}"
        except Exception as exc:
            logger.exception("Wallet scorer reasoning generation failed", exc_info=exc)
            return f"自動規則：{decision}"

    def _list_evaluable_wallets(self) -> list[WalletScore]:
        return self._addresses_repo.list_evaluable_wallets()

    def _weekly_metrics(self, address: str) -> dict[str, float | int]:
        trades = self._wallet_trades(hours=24 * 7, address=address)
        if not trades:
            return {"weekly_trades": 0, "weekly_win_rate": 0.0}

        rois = [self._trade_roi(trade) for trade in trades]
        wins = [roi for roi in rois if roi is not None and roi > 0]
        return {
            "weekly_trades": len(trades),
            "weekly_win_rate": round(len(wins) / len(trades), 4),
        }

    def _count_consecutive_losses(self, address: str) -> int:
        consecutive_losses = 0
        for trade in self._wallet_trades(hours=24 * 30, address=address):
            roi = self._trade_roi(trade)
            if roi is None:
                continue
            if roi < 0:
                consecutive_losses += 1
            else:
                break
        return consecutive_losses

    def _wallet_trades(self, *, hours: int, address: str) -> list[dict]:
        trades = self._trades_repo.recent_trades(hours=hours)
        if not isinstance(trades, list):
            return []
        return [trade for trade in trades if trade["source_wallet"] == address]

    @staticmethod
    def _trade_roi(trade: dict) -> float | None:
        raw = trade.get("pre_trade_mid_price")
        if raw is None:
            return None
        mid_price = float(raw)
        if mid_price == 0:
            return None
        return (float(trade["price"]) - mid_price) / mid_price

    @staticmethod
    def _extract_text(response: Any) -> str:
        content = getattr(response, "content", [])
        parts = [getattr(item, "text", "").strip() for item in content]
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _bounded_ratio(value: Any) -> float:
        numeric = float(value)
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _non_negative_float(value: Any) -> float:
        return max(0.0, float(value))
