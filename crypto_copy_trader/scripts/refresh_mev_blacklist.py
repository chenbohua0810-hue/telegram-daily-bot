from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reporting import TelegramNotifier
from storage import AddressesRepo

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _chain_for_address(address: str) -> str:
    return "eth" if address.startswith("0x") else "sol"


def _existing_entries_by_address(existing: dict) -> dict[str, tuple[str, dict]]:
    result: dict[str, tuple[str, dict]] = {}
    for key in ("entries", "eth", "bsc", "sol"):
        for entry in existing.get(key, []) or []:
            address = str(entry["address"]).lower()
            result[address] = (key, {**entry, "address": address})
    return result


def merge_blacklist_entries(existing: dict, new_entries: list[dict], *, today: str) -> tuple[dict, dict[str, int]]:
    by_address = _existing_entries_by_address(existing)
    added = 0
    updated = 0
    for entry in new_entries:
        address = str(entry["address"]).lower()
        incoming = {**entry, "address": address, "last_seen_utc": today}
        if address not in by_address:
            bucket = "entries" if "entries" in existing else _chain_for_address(address)
            by_address[address] = (bucket, {"first_seen_utc": today, **incoming})
            added += 1
            continue
        bucket, existing_entry = by_address[address]
        existing_confidence = str(existing_entry.get("confidence", "low"))
        incoming_confidence = str(incoming.get("confidence", "low"))
        confidence = existing_confidence
        if CONFIDENCE_RANK.get(incoming_confidence, 0) > CONFIDENCE_RANK.get(existing_confidence, 0):
            confidence = incoming_confidence
        by_address[address] = (
            bucket,
            {**existing_entry, **incoming, "confidence": confidence, "first_seen_utc": existing_entry.get("first_seen_utc", today)},
        )
        updated += 1

    merged = {key: value for key, value in existing.items() if key not in ("entries", "eth", "bsc", "sol")}
    merged["_meta"] = {**existing.get("_meta", {}), "last_updated_utc": today}
    buckets: dict[str, list[dict]] = {"entries": [], "eth": [], "bsc": [], "sol": []}
    for bucket, entry in by_address.values():
        target_bucket = bucket if bucket in buckets else "entries"
        buckets[target_bucket].append(entry)
    for key, values in buckets.items():
        if key in existing or values:
            merged[key] = sorted(values, key=lambda item: item["address"])
    return merged, {"added": added, "updated": updated}


def atomic_write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(target)


async def retire_matching_active_wallets(addresses_repo: AddressesRepo, blacklist_addresses: set[str], decisions_path: str, notifier: Any) -> int:
    matches = [wallet for wallet in addresses_repo.list_active() if wallet.address.lower() in blacklist_addresses]
    decision_file = Path(decisions_path)
    decision_file.parent.mkdir(parents=True, exist_ok=True)
    for wallet in matches:
        addresses_repo.set_status(wallet.address, "retired")
        payload = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "address": wallet.address,
            "decision": "retire",
            "reason": "mev_blacklist_match",
        }
        with decision_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        notify = getattr(notifier, "notify_risk_alert", None)
        if notify is not None:
            await notify(f"MEV blacklist matched active wallet {wallet.address}; auto-retired")
    return len(matches)


def entries_from_dune_rows(rows: list[dict], *, source: str, category: str, today: str) -> list[dict]:
    result = []
    for row in rows:
        address = str(row.get("address", "")).lower()
        profit = float(row.get("profit_30d", row.get("profit_usd_30d", 0.0)) or 0.0)
        trades = int(row.get("sandwich_count", row.get("trades_30d", 0)) or 0)
        if not address or (profit < 5000 and trades < 20):
            continue
        confidence = "high" if category == "sandwich" and profit >= 20000 else "medium"
        result.append({
            "address": address,
            "label": f"Auto-detected MEV ({source})",
            "category": category,
            "confidence": confidence,
            "source": source,
            "first_seen_utc": today,
            "last_seen_utc": today,
            "profit_usd_30d": profit,
        })
    return result


def fetch_dune_entries(today: str) -> list[dict]:
    # CLI integration intentionally small and testable. Production users can wrap this with DUNE_API_KEY auth.
    commands = [
        ("scripts/sql/mev_sandwich_eth_30d.sql", "dune.mev.sandwich_aggregated_summary", "sandwich"),
        ("scripts/sql/mev_highfreq_eth_30d.sql", "dune.dex.trades.high_freq", "arbitrage"),
    ]
    entries: list[dict] = []
    for sql_path, source, category in commands:
        completed = subprocess.run(["dune", "query", "execute", "--file", sql_path, "--json"], capture_output=True, text=True, check=True)
        rows = json.loads(completed.stdout or "[]")
        entries.extend(entries_from_dune_rows(rows, source=source, category=category, today=today))
    return entries


async def fetch_libmev_entries(api_url: str, today: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(api_url, params={"timeframe": "month", "limit": 100})
        response.raise_for_status()
        payload = response.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    return entries_from_dune_rows(
        [
            {"address": row.get("searcher_address"), "profit_30d": row.get("profit", row.get("profit_usd_30d", 0.0)), "sandwich_count": 20}
            for row in rows
        ],
        source="libmev.api.leaderboard",
        category="unknown_mev",
        today=today,
    )


async def refresh(args: argparse.Namespace) -> dict[str, int]:
    today = datetime.now(timezone.utc).date().isoformat()
    path = Path(args.blacklist_path)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"entries": []}
    try:
        entries = fetch_dune_entries(today)
    except Exception:
        entries = await fetch_libmev_entries(args.libmev_api_url, today)
    if len(entries) > args.max_new_entries:
        raise RuntimeError("refusing to write suspiciously large MEV update")
    merged, stats = merge_blacklist_entries(existing, entries, today=today)
    atomic_write_json(args.blacklist_path, merged)
    addresses_repo = AddressesRepo(args.addresses_db)
    notifier = TelegramNotifier(args.telegram_bot_token, args.telegram_chat_id) if args.telegram_bot_token and args.telegram_chat_id else None
    blacklist_addresses = set()
    for key in ("entries", "eth", "bsc", "sol"):
        blacklist_addresses.update(str(entry["address"]).lower() for entry in merged.get(key, []) or [])
    matched = await retire_matching_active_wallets(addresses_repo, blacklist_addresses, args.decisions_path, notifier)
    return {**stats, "matched": matched}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh MEV blacklist")
    parser.add_argument("--blacklist-path", default="data/mev_blacklist.json")
    parser.add_argument("--addresses-db", default="data/addresses.db")
    parser.add_argument("--decisions-path", default="data/wallet_decisions.jsonl")
    parser.add_argument("--libmev-api-url", default=os.getenv("MEV_REFRESH_LIBMEV_API_URL", "https://api.libmev.com/v1/bundles/leaderboard"))
    parser.add_argument("--max-new-entries", type=int, default=int(os.getenv("MEV_REFRESH_MAX_NEW_ENTRIES", "200")))
    parser.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""))
    parser.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_CHAT_ID", ""))
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(refresh(parse_args())), sort_keys=True))
