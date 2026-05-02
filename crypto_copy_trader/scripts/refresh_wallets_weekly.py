from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import WalletScore
from reporting import TelegramNotifier
from storage import AddressesRepo


@dataclass(frozen=True)
class CandidateRefresh:
    address: str
    chain: str
    pnl_180d: float
    win_rate: float
    trade_count: int


@dataclass(frozen=True)
class RefreshSummary:
    promoted: int
    demoted: int
    retired: int
    unchanged: int

    def format(self) -> str:
        return f"Wallet refresh: promoted {self.promoted}, demoted {self.demoted}, retired {self.retired}, unchanged {self.unchanged}"


def refresh_wallet_statuses(
    repo: AddressesRepo,
    *,
    performance_30d: dict[str, dict[str, float]],
    top_candidates: list[CandidateRefresh],
    prior_watch_failures: dict[str, int] | None = None,
    now: datetime | None = None,
) -> RefreshSummary:
    prior_failures = prior_watch_failures or {}
    demoted = 0
    retired = 0
    unchanged = 0
    promoted = 0

    evaluable = repo.list_evaluable_wallets()
    for wallet in evaluable:
        performance = performance_30d.get(wallet.address, {})
        is_degraded = float(performance.get("pnl_usd", 0.0)) < 0 or float(performance.get("win_rate", wallet.recent_win_rate)) < 0.45
        if wallet.status == "active" and is_degraded:
            repo.set_status(wallet.address, "watch")
            repo.append_history(wallet.address, wallet, "watch", "weekly_refresh_degraded", evaluated_at=now)
            demoted += 1
        elif wallet.status == "watch" and is_degraded and prior_failures.get(wallet.address, 0) >= 1:
            repo.set_status(wallet.address, "retired")
            repo.append_history(wallet.address, wallet, "retire", "weekly_refresh_second_degraded_week", evaluated_at=now)
            retired += 1
        else:
            unchanged += 1

    existing = {wallet.address for wallet in repo.list_evaluable_wallets()}
    for candidate in top_candidates[:50]:
        if candidate.address in existing or repo.get_wallet(candidate.address) is not None:
            continue
        repo.upsert_wallet(
            WalletScore(
                address=candidate.address,
                chain=candidate.chain,  # type: ignore[arg-type]
                win_rate=candidate.win_rate,
                trade_count=candidate.trade_count,
                max_drawdown=0.40,
                funds_usd=max(0.0, candidate.pnl_180d),
                recent_win_rate=candidate.win_rate,
                trust_level="low",
                status="watch",
                binance_listable_pnl_180d=max(0.0, candidate.pnl_180d),
            )
        )
        promoted += 1

    return RefreshSummary(promoted=promoted, demoted=demoted, retired=retired, unchanged=unchanged)


def load_candidates_json(path: str) -> list[CandidateRefresh]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    return [
        CandidateRefresh(
            address=str(row["address"]),
            chain=str(row.get("chain", "eth")),
            pnl_180d=float(row.get("pnl_180d", row.get("realized_pnl_usd", 0.0))),
            win_rate=float(row.get("win_rate", 0.0)),
            trade_count=int(row.get("trade_count", 0)),
        )
        for row in rows
    ]


def load_performance_json(path: str) -> dict[str, dict[str, float]]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return {str(address): {str(k): float(v) for k, v in values.items()} for address, values in payload.items()}


def load_watch_failures_json(path: str) -> dict[str, int]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return {str(address): int(value) for address, value in payload.items()}

async def run(args: argparse.Namespace) -> RefreshSummary:
    repo = AddressesRepo(args.db)
    summary = refresh_wallet_statuses(
        repo,
        performance_30d=load_performance_json(args.performance_json),
        top_candidates=load_candidates_json(args.candidates_json),
        prior_watch_failures=load_watch_failures_json(args.watch_failures_json),
        now=datetime.now(timezone.utc),
    )
    if args.telegram_bot_token and args.telegram_chat_id:
        notifier = TelegramNotifier(args.telegram_bot_token, args.telegram_chat_id)
        await notifier.notify_risk_alert(summary.format())
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weekly wallet refresh")
    parser.add_argument("--db", default="data/addresses.db")
    parser.add_argument("--candidates-json", default="data/dune_top_wallets_180d.json")
    parser.add_argument("--performance-json", default="data/wallet_performance_30d.json")
    parser.add_argument("--watch-failures-json", default="data/watch_failures.json")
    parser.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""))
    parser.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_CHAT_ID", ""))
    return parser.parse_args()


if __name__ == "__main__":
    print(asyncio.run(run(parse_args())).format())
