"""
Stage-2 wallet pipeline: evaluate status="watch" wallets with 90-180 day
historical data and promote to active, keep as watch, or retire.

Usage:
  python scripts/promote_wallets.py --chain sol
  python scripts/promote_wallets.py --chain eth --csv ./dune_eth_180d.csv
  python scripts/promote_wallets.py --chain all --csv ./dune_eth_180d.csv
  python scripts/promote_wallets.py --chain all --csv ./dune_eth_180d.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import WalletScore, classify_trust_level
from storage import AddressesRepo

# ── constants ─────────────────────────────────────────────────────────────────

MIN_REALIZED_PNL_USD = 50_000
MIN_TRADE_COUNT = 50
MIN_TOKEN_DIVERSITY = 8
MAX_DRAWDOWN_RATIO = 0.35
MIN_SHARPE_LIKE = 2.0
MIN_SHARPE_LIKE_WATCH = 1.2
MIN_RECENT_ACTIVITY_DAYS = 14   # must have traded within this many days to promote
MAX_INACTIVE_DAYS = 30          # retire threshold: no trade in this many days

KNOWN_CEX_ADDRESSES: frozenset[str] = frozenset({
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "0x28c6c06298d514db089934071355e5743bf21d60",
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",
})

GMGN_SOL_WALLET_URL = (
    "https://gmgn.ai/defi/quotation/v1/smartmoney/sol/walletNew/{address}?period=30d"
)
BIRDEYE_TXS_URL = "https://public-api.birdeye.so/trader/txs/seek_by_time"
SOL_MINT = "So11111111111111111111111111111111111111112"

DEFAULT_DB = "data/addresses.db"


# ── internal dataclasses ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class HistoryRecord:
    address: str
    chain: str
    realized_pnl_usd: float
    win_rate: float
    trade_count: int
    token_diversity: int
    pnl_daily_series: tuple[float, ...]
    last_trade_days_ago: int
    funding_source: Optional[str]
    gmgn_verified: bool = True   # False = Birdeye fallback, PnL not computable


@dataclass(frozen=True)
class Metrics:
    realized_pnl_usd: float
    sharpe_like: float
    max_drawdown_ratio: float
    trade_count: int
    token_diversity: int
    last_trade_days_ago: int
    funding_source: Optional[str]
    gmgn_verified: bool = True


class DecisionKind(Enum):
    PROMOTE = "active"
    HOLD = "watch"
    RETIRE = "retired"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    reason: str


# ── pure computation functions ────────────────────────────────────────────────


def compute_sharpe_like(pnl_daily_series: tuple[float, ...]) -> float:
    if not pnl_daily_series:
        return 0.0

    cumulative: list[float] = []
    running = 0.0
    for daily in pnl_daily_series:
        running += daily
        cumulative.append(running)

    total_pnl = cumulative[-1]
    peak_equity = max(cumulative)

    if peak_equity <= 0:
        return 0.0

    peak_idx = cumulative.index(peak_equity)
    post_peak = cumulative[peak_idx:]
    max_dd_usd = peak_equity - min(post_peak)

    if max_dd_usd == 0:
        return float("inf")

    return total_pnl / max_dd_usd


def compute_max_drawdown_ratio(pnl_daily_series: tuple[float, ...]) -> float:
    if not pnl_daily_series:
        return 0.0

    cumulative: list[float] = []
    running = 0.0
    for daily in pnl_daily_series:
        running += daily
        cumulative.append(running)

    peak_equity = max(cumulative)
    if peak_equity <= 0:
        return 1.0

    peak_idx = cumulative.index(peak_equity)
    post_peak = cumulative[peak_idx:]
    max_dd_usd = peak_equity - min(post_peak)

    return min(max(max_dd_usd / peak_equity, 0.0), 1.0)


def compute_metrics(history: HistoryRecord) -> Metrics:
    return Metrics(
        realized_pnl_usd=history.realized_pnl_usd,
        sharpe_like=compute_sharpe_like(history.pnl_daily_series),
        max_drawdown_ratio=compute_max_drawdown_ratio(history.pnl_daily_series),
        trade_count=history.trade_count,
        token_diversity=history.token_diversity,
        last_trade_days_ago=history.last_trade_days_ago,
        funding_source=history.funding_source,
        gmgn_verified=history.gmgn_verified,
    )


def detect_sybil_clusters(
    candidates: list[tuple[WalletScore, HistoryRecord]],
) -> dict[str, str]:
    """Returns address -> cluster_leader_address for all non-leader duplicates."""
    source_to_members: dict[str, list[tuple[str, float]]] = {}

    for wallet, history in candidates:
        fs = history.funding_source
        if not fs or fs in KNOWN_CEX_ADDRESSES:
            continue
        source_to_members.setdefault(fs, []).append(
            (wallet.address, history.realized_pnl_usd)
        )

    address_to_leader: dict[str, str] = {}

    for members in source_to_members.values():
        if len(members) <= 1:
            continue
        leader_addr = max(members, key=lambda x: x[1])[0]
        for addr, _ in members:
            address_to_leader[addr] = leader_addr

    return address_to_leader


def decide(
    wallet: WalletScore,
    metrics: Metrics,
    cluster_role: dict[str, str],
) -> Decision:
    addr = wallet.address

    if metrics.trade_count < 20 or metrics.last_trade_days_ago > MAX_INACTIVE_DAYS:
        return Decision(
            DecisionKind.RETIRE,
            f"inactive (last trade {metrics.last_trade_days_ago}d ago, trades={metrics.trade_count})",
        )

    if metrics.realized_pnl_usd < 0 or metrics.max_drawdown_ratio > 0.50:
        return Decision(
            DecisionKind.RETIRE,
            f"unprofitable (pnl=${metrics.realized_pnl_usd:.0f}, drawdown={metrics.max_drawdown_ratio:.2%})",
        )

    if addr in cluster_role and cluster_role[addr] != addr:
        leader = cluster_role[addr]
        return Decision(
            DecisionKind.RETIRE,
            f"sybil duplicate (cluster leader {leader[:8]}...)",
        )

    # Activity-based promotion for Birdeye fallback wallets (PnL not computable from tx data).
    # Uses MAX_INACTIVE_DAYS (30d) instead of MIN_RECENT_ACTIVITY_DAYS (14d) because Birdeye
    # gainers-losers may surface wallets whose last trade was 2-3 weeks ago.
    if not metrics.gmgn_verified:
        activity_ok = (
            metrics.trade_count >= MIN_TRADE_COUNT
            and metrics.token_diversity >= MIN_TOKEN_DIVERSITY
            and metrics.last_trade_days_ago <= MAX_INACTIVE_DAYS
        )
        if activity_ok:
            return Decision(
                DecisionKind.PROMOTE,
                f"activity-based (trades={metrics.trade_count} diversity={metrics.token_diversity}; pnl unverified)",
            )
        return Decision(
            DecisionKind.HOLD,
            f"activity thresholds not met (trades={metrics.trade_count} diversity={metrics.token_diversity})",
        )

    passes_all = (
        metrics.realized_pnl_usd >= MIN_REALIZED_PNL_USD
        and metrics.trade_count >= MIN_TRADE_COUNT
        and metrics.token_diversity >= MIN_TOKEN_DIVERSITY
        and metrics.max_drawdown_ratio <= MAX_DRAWDOWN_RATIO
        and metrics.last_trade_days_ago <= MIN_RECENT_ACTIVITY_DAYS
    )

    if passes_all:
        if metrics.sharpe_like >= MIN_SHARPE_LIKE:
            return Decision(
                DecisionKind.PROMOTE,
                f"pnl=${metrics.realized_pnl_usd:.0f} sharpe={metrics.sharpe_like:.1f}",
            )
        if metrics.sharpe_like >= MIN_SHARPE_LIKE_WATCH:
            return Decision(
                DecisionKind.HOLD,
                f"borderline sharpe={metrics.sharpe_like:.1f} (kept watching)",
            )
        return Decision(
            DecisionKind.RETIRE,
            f"low sharpe ({metrics.sharpe_like:.1f} < {MIN_SHARPE_LIKE_WATCH})",
        )

    return Decision(
        DecisionKind.HOLD,
        f"thresholds not met (pnl=${metrics.realized_pnl_usd:.0f}"
        f" trades={metrics.trade_count} diversity={metrics.token_diversity}"
        f" dd={metrics.max_drawdown_ratio:.2%})",
    )


# ── data loading ──────────────────────────────────────────────────────────────


def load_watch_wallets(repo: AddressesRepo, chain: str) -> list[WalletScore]:
    all_wallets = repo.list_evaluable_wallets()
    watch = [w for w in all_wallets if w.status == "watch"]
    if chain != "all":
        watch = [w for w in watch if w.chain == chain]
    return watch


def _parse_pnl_series(raw: object) -> tuple[float, ...]:
    if isinstance(raw, (list, tuple)):
        result = []
        for item in raw:
            if isinstance(item, (int, float)):
                result.append(float(item))
            elif isinstance(item, dict):
                val = item.get("pnl") or item.get("value") or item.get("amount")
                if val is not None:
                    result.append(float(val))
        return tuple(result)
    if isinstance(raw, str):
        if raw.startswith("["):
            try:
                return _parse_pnl_series(json.loads(raw))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        try:
            return tuple(float(x) for x in raw.split("|") if x.strip())
        except ValueError:
            return ()
    return ()


def _http_client() -> httpx.Client:
    ua = os.getenv(
        "HTTP_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    )
    return httpx.Client(timeout=10.0, headers={"User-Agent": ua, "Accept": "application/json"})


def _fetch_with_retry(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    extra_headers: dict | None = None,
) -> dict:
    for attempt in range(3):
        try:
            resp = client.get(url, params=params, headers=extra_headers or {})
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError(
                    f"fetch failed after 3 attempts: {url}: {exc}"
                ) from exc
            wait = 2**attempt
            print(f"  ⚠ retry {attempt + 1}/3: {exc} (wait {wait}s)")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_history_sol(
    address: str, client: httpx.Client, cache_dir: str
) -> HistoryRecord | None:
    url = GMGN_SOL_WALLET_URL.format(address=address)
    gmgn_raw = None
    is_403 = False
    try:
        gmgn_raw = _fetch_with_retry(client, url)
    except Exception as exc:
        print(f"  ⚠ GMGN fetch failed for {address[:8]}...: {exc}")
        is_403 = "403" in str(exc)
    finally:
        time.sleep(1)

    if gmgn_raw is None:
        if is_403:
            api_key = os.getenv("BIRDEYE_API_KEY", "")
            if api_key:
                print(f"  → Birdeye txs fallback for {address[:8]}...")
                return fetch_history_sol_birdeye(address, api_key, client, cache_dir)
        return None

    cache_path = os.path.join(cache_dir, f"{address}.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(gmgn_raw, f, separators=(",", ":"))

    data = gmgn_raw.get("data") or {}

    try:
        realized_pnl = float(data.get("realized_profit") or 0)
        win_rate = min(float(data.get("winrate") or 0), 1.0)
        trade_count = int(data.get("txs") or 0)
        token_diversity = int(data.get("token_num_30d") or data.get("token_num") or 0)
        pnl_series = _parse_pnl_series(data.get("pnl_30d_by_day") or [])

        last_active_ts = data.get("last_active_timestamp")
        if last_active_ts:
            now_ts = datetime.now(timezone.utc).timestamp()
            last_trade_days = int((now_ts - int(last_active_ts)) / 86400)
        else:
            last_trade_days = 0

        return HistoryRecord(
            address=address,
            chain="sol",
            realized_pnl_usd=realized_pnl,
            win_rate=win_rate,
            trade_count=trade_count,
            token_diversity=token_diversity,
            pnl_daily_series=pnl_series,
            last_trade_days_ago=last_trade_days,
            funding_source=None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(f"  ⚠ parse error for {address[:8]}...: {exc}")
        return None


def fetch_history_sol_birdeye(
    address: str, api_key: str, client: httpx.Client, cache_dir: str
) -> HistoryRecord | None:
    """Fetch 30-day swap history from Birdeye as GMGN fallback.

    Computes realized PnL, win_rate, token_diversity, and daily PnL series
    from raw swap transactions (quote_value - base_value per trade).
    """
    after_time = int(time.time()) - 86400 * 30
    params = {"address": address, "tx_type": "swap", "limit": 100, "after_time": after_time}
    headers = {"X-API-KEY": api_key, "x-chain": "solana"}
    try:
        raw = _fetch_with_retry(client, BIRDEYE_TXS_URL, params=params, extra_headers=headers)
    except Exception as exc:
        print(f"  ⚠ Birdeye txs failed for {address[:8]}...: {exc}")
        return None

    cache_path = os.path.join(cache_dir, f"{address}_birdeye.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, separators=(",", ":"))

    items = (raw.get("data") or {}).get("items") or []
    if not items:
        return None

    # AMM swaps: quote_value - base_value is always ~0 by definition (both sides valued at
    # execution price). Realized PnL requires FIFO cost tracking across time — not possible
    # from a single 30d window when buys may have occurred earlier.
    # We compute activity signals only; PnL is set to 0 (neutral) and gmgn_verified=False
    # so decide() uses activity-based promotion instead of PnL-based criteria.
    token_set: set[str] = set()
    last_ts = 0
    trades_seen: set[str] = set()

    for tx in items:
        ts = tx.get("block_unix_time") or 0
        last_ts = max(last_ts, ts)

        for side in (tx.get("base") or {}, tx.get("quote") or {}):
            addr = side.get("address") or ""
            if addr and addr != SOL_MINT:
                token_set.add(addr)

        tx_sig = tx.get("txHash") or tx.get("tx_hash") or str(ts)
        trades_seen.add(tx_sig)

    trade_count = len(items)
    last_trade_days_ago = int((time.time() - last_ts) / 86400) if last_ts else 0

    return HistoryRecord(
        address=address,
        chain="sol",
        realized_pnl_usd=0.0,
        win_rate=0.0,
        trade_count=trade_count,
        token_diversity=len(token_set),
        pnl_daily_series=(),
        last_trade_days_ago=last_trade_days_ago,
        funding_source=None,
        gmgn_verified=False,
    )


def load_history_eth_csv(csv_path: str) -> dict[str, HistoryRecord]:
    result: dict[str, HistoryRecord] = {}

    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    address = row["address"].strip()
                    last_trade_raw = row.get("last_trade_days_ago", "").strip()
                    result[address] = HistoryRecord(
                        address=address,
                        chain="eth",
                        realized_pnl_usd=float(row["realized_pnl_usd"]),
                        win_rate=min(float(row.get("win_rate") or 0), 1.0),
                        trade_count=int(row.get("trade_count") or 0),
                        token_diversity=int(row.get("token_diversity") or 0),
                        pnl_daily_series=_parse_pnl_series(
                            row.get("pnl_daily_series", "")
                        ),
                        last_trade_days_ago=int(last_trade_raw) if last_trade_raw else 0,
                        funding_source=row.get("funding_source") or None,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    print(f"  ⚠ CSV row parse error: {exc}")
    except FileNotFoundError:
        print(f"  ✗ CSV not found: {csv_path}")

    return result


# ── decision application ──────────────────────────────────────────────────────


def apply_decision(
    repo: AddressesRepo,
    wallet: WalletScore,
    decision: Decision,
    history: HistoryRecord | None,
    dry_run: bool,
) -> WalletScore | None:
    if decision.kind == DecisionKind.HOLD:
        return None

    if decision.kind == DecisionKind.PROMOTE and history is not None:
        dd_ratio = compute_max_drawdown_ratio(history.pnl_daily_series)
        trust = classify_trust_level(history.win_rate, history.trade_count, dd_ratio)
        new_wallet = replace(
            wallet,
            win_rate=history.win_rate,
            trade_count=history.trade_count,
            max_drawdown=min(dd_ratio, 1.0),
            recent_win_rate=history.win_rate,
            trust_level=trust,
            status="active",
        )
    else:
        new_wallet = replace(wallet, status=decision.kind.value)

    if not dry_run:
        repo.upsert_wallet(new_wallet)

    return new_wallet


# ── main dispatch ─────────────────────────────────────────────────────────────


def run_promote(args: argparse.Namespace) -> None:
    repo = AddressesRepo(args.db)
    watch_wallets = load_watch_wallets(repo, args.chain)

    sol_wallets = [w for w in watch_wallets if w.chain == "sol"]
    eth_wallets = [w for w in watch_wallets if w.chain == "eth"]
    bsc_wallets = [w for w in watch_wallets if w.chain == "bsc"]

    print(
        f"[promote] loaded {len(watch_wallets)} watch wallets"
        f" (sol={len(sol_wallets)}, eth={len(eth_wallets)})"
    )
    if bsc_wallets:
        print(
            f"[promote] TODO: BSC support not implemented,"
            f" skipping {len(bsc_wallets)} BSC wallets"
        )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    cache_dir = os.path.join("data", "raw", "promote", ts)
    os.makedirs(cache_dir, exist_ok=True)

    histories: dict[str, HistoryRecord] = {}

    if sol_wallets:
        print(f"[promote] fetching historical data for {len(sol_wallets)} SOL wallets...")
        with _http_client() as client:
            for wallet in sol_wallets:
                record = fetch_history_sol(wallet.address, client, cache_dir)
                if record is not None:
                    histories[wallet.address] = record
                else:
                    print(f"  ⚠ no historical data for {wallet.address}, kept as watch")

    if eth_wallets:
        if not args.csv:
            print(
                f"[promote] ⚠ --csv required for ETH wallets,"
                f" skipping {len(eth_wallets)} ETH wallets"
            )
        else:
            print(f"[promote] loading ETH history from {args.csv}...")
            shutil.copy2(args.csv, os.path.join(cache_dir, "dune_eth.csv"))
            eth_histories = load_history_eth_csv(args.csv)
            for wallet in eth_wallets:
                if wallet.address in eth_histories:
                    histories[wallet.address] = eth_histories[wallet.address]
                else:
                    print(f"  ⚠ no historical data for {wallet.address}, kept as watch")

    candidates = [
        (w, histories[w.address]) for w in watch_wallets if w.address in histories
    ]

    cluster_role = detect_sybil_clusters(candidates)
    demoted_count = sum(1 for addr, leader in cluster_role.items() if addr != leader)
    if cluster_role:
        print(f"[promote] sybil clusters: {demoted_count} wallets demoted")

    all_decisions: list[tuple[WalletScore, Metrics | None, Decision]] = []

    for wallet in watch_wallets:
        if wallet.address not in histories:
            all_decisions.append((wallet, None, Decision(DecisionKind.HOLD, "no historical data")))
            continue
        metrics = compute_metrics(histories[wallet.address])
        decision = decide(wallet, metrics, cluster_role)
        all_decisions.append((wallet, metrics, decision))

    _print_decisions(all_decisions, args.dry_run)

    if not args.dry_run:
        for wallet, _metrics, decision in all_decisions:
            history = histories.get(wallet.address)
            apply_decision(repo, wallet, decision, history, dry_run=False)

    _save_audit(all_decisions, cache_dir)


def _print_decisions(
    all_decisions: list[tuple[WalletScore, Metrics | None, Decision]],
    dry_run: bool,
) -> None:
    print("[promote] decisions:")
    promoted = held = retired = 0

    for wallet, metrics, decision in all_decisions:
        label = decision.kind.name.ljust(7)
        addr_short = wallet.address[:8] + "..."

        if metrics is not None:
            sharpe_val = metrics.sharpe_like
            sharpe_str = "inf" if sharpe_val == float("inf") else f"{sharpe_val:.1f}"
            pnl_k = metrics.realized_pnl_usd / 1000
            extra = f"pnl=${pnl_k:.0f}k sharpe={sharpe_str} trust={wallet.trust_level}"
        else:
            extra = ""

        print(f"  {label}  {addr_short}  {wallet.chain}  {extra}  → {decision.reason}")

        if decision.kind == DecisionKind.PROMOTE:
            promoted += 1
        elif decision.kind == DecisionKind.HOLD:
            held += 1
        else:
            retired += 1

    suffix = "  (dry-run: no writes)" if dry_run else ""
    print(f"Summary: {promoted} promoted / {held} kept watch / {retired} retired{suffix}")


def _save_audit(
    all_decisions: list[tuple[WalletScore, Metrics | None, Decision]],
    cache_dir: str,
) -> None:
    audit = []
    for wallet, metrics, decision in all_decisions:
        entry: dict = {
            "address": wallet.address,
            "chain": wallet.chain,
            "decision": decision.kind.value,
            "reason": decision.reason,
        }
        if metrics is not None:
            sharpe = metrics.sharpe_like
            entry["metrics"] = {
                "realized_pnl_usd": metrics.realized_pnl_usd,
                "sharpe_like": "inf" if sharpe == float("inf") else sharpe,
                "max_drawdown_ratio": metrics.max_drawdown_ratio,
                "trade_count": metrics.trade_count,
                "last_trade_days_ago": metrics.last_trade_days_ago,
            }
        audit.append(entry)

    decisions_path = os.path.join(cache_dir, "decisions.json")
    with open(decisions_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)
    print(f"[promote] audit log → {decisions_path}")


def main(args: argparse.Namespace) -> None:
    run_promote(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage-2 wallet promotion pipeline")
    parser.add_argument(
        "--chain",
        choices=["sol", "eth", "bsc", "all"],
        default="all",
        help="Which chain to process",
    )
    parser.add_argument("--csv", help="Path to Dune CSV for ETH wallets")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite DB path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print decisions without writing to DB",
    )
    main(parser.parse_args())
