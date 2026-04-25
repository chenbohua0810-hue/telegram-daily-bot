"""
Stage-1 wallet pipeline: fetch candidate wallets from GMGN (SOL),
Birdeye (SOL fallback), and Dune CSV (ETH), apply loose discovery
thresholds, and persist as status="watch".

Dune query reference (run manually, export CSV):
  SELECT address, realized_pnl_usd, win_rate, trade_count, max_drawdown,
         funds_usd, token_diversity
  FROM dex_traders
  WHERE realized_pnl_usd > 50000 AND trade_count >= 30 AND token_diversity >= 8
  LIMIT 200

Usage:
  python scripts/discover_wallets.py --source gmgn-sol --limit 50
  python scripts/discover_wallets.py --source birdeye-sol --limit 50
  python scripts/discover_wallets.py --source birdeye-sol-active --limit 10
  python scripts/discover_wallets.py --source dune-csv-eth --csv ./dune_eth_180d.csv
  python scripts/discover_wallets.py --source all --limit 50 --csv ./dune_eth_180d.csv
  python scripts/discover_wallets.py --source all --limit 50 --csv ./dune_eth_180d.csv --dry-run
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
from typing import Optional

import httpx

# Allow `from models import ...` when running from crypto_copy_trader/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import WalletScore, classify_trust_level
from storage import AddressesRepo

# ── LST / SOL mint constants (used by enrich step) ────────────────────────────
LST_MINTS_SOL: frozenset[str] = frozenset({
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",   # mSOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",   # stSOL
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",   # jitoSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",    # bSOL
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",   # INF
    "rdLGT5oMFHn9sFjEe4KxF9bEBXMCGx3gF2gjmGZ8V3i",    # rdlgtSOL (verify from DB)
})

SOL_NATIVE_MINTS: frozenset[str] = frozenset({
    "So11111111111111111111111111111111111111112",   # wSOL
    "11111111111111111111111111111111",              # native SOL program
})

MAX_LST_SWAP_RATIO = 0.70   # ratio > this → wallet is LST-only, drop
MIN_SAMPLED_TXS = 10        # fewer txs → insufficient sample, keep with diversity=None
TX_SAMPLE_WINDOW_DAYS = 7   # align with Birdeye 1W top traders window

# ── blocklist ─────────────────────────────────────────────────────────────────
BLOCKLIST_SOL: frozenset[str] = frozenset({
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter v6
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",   # Raydium AMM v4
})
BLOCKLIST_ETH: frozenset[str] = frozenset({
    "0x28c6c06298d514db089934071355e5743bf21d60",    # Binance 14
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",    # Uniswap Universal Router
})

# ── discovery thresholds (intentionally loose) ────────────────────────────────
MIN_WIN_RATE = 0.50
MIN_TRADE_COUNT = 30
MIN_TOKEN_DIVERSITY = 5
MIN_FUNDS_USD = 20_000.0
MAX_DRAWDOWN_IF_KNOWN = 0.40

DEFAULT_DB = "data/addresses.db"
DEFAULT_LIMIT = 50

GMGN_SOL_URL = "https://gmgn.ai/defi/quotation/v1/rank/sol/wallets/30d"
BIRDEYE_SOL_URL = "https://public-api.birdeye.so/trader/gainers-losers"
BIRDEYE_TXS_URL = "https://public-api.birdeye.so/trader/txs/seek_by_time"


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    address: str
    chain: str
    win_rate: float
    trade_count: int
    funds_usd: float
    token_diversity: Optional[int]    # None = not provided by source
    max_drawdown: Optional[float]     # None = not provided by source
    recent_win_rate: Optional[float]  # None = not provided by source
    source: str


def _utc_now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _http_client() -> httpx.Client:
    ua = os.getenv("HTTP_USER_AGENT", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    return httpx.Client(timeout=10.0, headers={"User-Agent": ua, "Accept": "application/json"})


def _fetch_with_retry(client: httpx.Client, url: str, params: dict | None = None, extra_headers: dict | None = None) -> dict:
    for attempt in range(3):
        try:
            resp = client.get(url, params=params, headers=extra_headers or {})
            if resp.status_code in (401, 403, 503):
                raise FetchError(f"HTTP {resp.status_code} from {url}")
            resp.raise_for_status()
            return resp.json()
        except FetchError:
            raise
        except Exception as exc:
            if attempt == 2:
                raise FetchError(f"fetch failed after 3 attempts: {url}: {exc}") from exc
            wait = 2 ** attempt
            print(f"  ⚠ retry {attempt + 1}/3 for {url}: {exc} (wait {wait}s)")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _cache_raw_json(source: str, ts: str, data: object) -> str:
    path = os.path.join("data", "raw", source, f"{ts}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    return path


def fetch_gmgn_sol(limit: int, ts: str) -> list[dict]:
    params = {"orderby": "pnl_30d", "direction": "desc", "limit": limit}
    with _http_client() as client:
        raw = _fetch_with_retry(client, GMGN_SOL_URL, params)
    path = _cache_raw_json("gmgn-sol", ts, raw)
    print(f"[gmgn-sol] fetched, cached → {path}")
    return (raw.get("data") or {}).get("rank") or []


def normalize_gmgn_sol(rows: list[dict]) -> list[Candidate]:
    result = []
    for row in rows:
        try:
            result.append(Candidate(
                address=row["wallet_address"],
                chain="sol",
                win_rate=min(float(row.get("winrate_30d") or 0), 1.0),
                trade_count=int(row.get("txs_30d") or 0),
                funds_usd=float(row.get("sol_balance") or 0),
                token_diversity=int(row["token_num_30d"]) if row.get("token_num_30d") is not None else None,
                max_drawdown=None,
                recent_win_rate=None,
                source="gmgn-sol",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[gmgn-sol] normalize skip: {exc}")
    return result


def fetch_birdeye_sol(
    limit: int,
    ts: str,
    sort_by: str = "PnL",
    time_frame: str = "1W",
    offset: int = 0,
) -> list[dict]:
    params = {"time_frame": time_frame, "sort_by": sort_by, "sort_type": "desc", "offset": offset, "limit": limit}
    api_key = os.getenv("BIRDEYE_API_KEY", "")
    extra = {"X-API-KEY": api_key, "x-chain": "solana"} if api_key else {"x-chain": "solana"}
    with _http_client() as client:
        raw = _fetch_with_retry(client, BIRDEYE_SOL_URL, params, extra_headers=extra)
    cache_tag = f"{ts}-{sort_by.lower()}-{time_frame.lower()}-off{offset}"
    path = _cache_raw_json("birdeye-sol", cache_tag, raw)
    print(f"[birdeye-sol] fetched sort_by={sort_by} time_frame={time_frame} offset={offset}, cached → {path}")
    return (raw.get("data") or {}).get("items") or raw.get("data") or []


def normalize_birdeye_sol(rows: list[dict]) -> list[Candidate]:
    result = []
    for row in rows:
        try:
            result.append(Candidate(
                address=row.get("address") or row["wallet"],
                chain="sol",
                # Birdeye gainers-losers does not expose win_rate; use 0.5 as conservative sentinel
                win_rate=min(float(row.get("winRate") or row.get("win_rate") or 0.5), 1.0),
                trade_count=int(row.get("tradeCount") or row.get("trade_count") or 0),
                funds_usd=float(row.get("volume") or row.get("pnl") or row.get("realizedPnl") or 0),
                token_diversity=None,   # not provided by Birdeye 1W endpoint
                max_drawdown=None,      # not provided
                recent_win_rate=None,
                source="birdeye-sol",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[birdeye-sol] normalize skip: {exc}")
    return result


def _is_lst_or_sol(mint: str) -> bool:
    return mint in LST_MINTS_SOL or mint in SOL_NATIVE_MINTS


def _classify_txs(items: list[dict]) -> tuple[int, set[str]]:
    """Return (lst_only_count, non_lst_mint_set) for a list of Birdeye swap txs."""
    lst_count = 0
    non_lst_mints: set[str] = set()
    for tx in items:
        base_mint  = (tx.get("base")  or {}).get("address") or ""
        quote_mint = (tx.get("quote") or {}).get("address") or ""
        if _is_lst_or_sol(base_mint) and _is_lst_or_sol(quote_mint):
            lst_count += 1
        for mint in (base_mint, quote_mint):
            if mint and not _is_lst_or_sol(mint):
                non_lst_mints.add(mint)
    return lst_count, non_lst_mints


def enrich_birdeye_sol_diversity(
    candidates: list[Candidate],
    client: httpx.Client,
) -> list[Candidate]:
    """Enrich Birdeye candidates with token_diversity; drop LST-only wallets."""
    api_key = os.getenv("BIRDEYE_API_KEY", "")
    headers = {"X-API-KEY": api_key, "x-chain": "solana"} if api_key else {"x-chain": "solana"}
    time_from = int(time.time()) - 86400 * TX_SAMPLE_WINDOW_DAYS
    result: list[Candidate] = []
    dropped = 0
    insufficient = 0

    for c in candidates:
        try:
            params = {"address": c.address, "tx_type": "swap", "limit": 50, "after_time": time_from}
            raw = _fetch_with_retry(client, BIRDEYE_TXS_URL, params=params, extra_headers=headers)
            items = (raw.get("data") or {}).get("items") or []
        except (FetchError, KeyError, ValueError) as exc:
            print(f"WARN {c.address[:10]} enrich failed: {exc}")
            result.append(c)
            continue

        n = len(items)
        if n < MIN_SAMPLED_TXS:
            print(f"NOTE {c.address[:10]} insufficient samples ({n})")
            result.append(c)
            insufficient += 1
            continue

        lst_count, non_lst_mints = _classify_txs(items)
        lst_ratio = lst_count / n
        if lst_ratio > MAX_LST_SWAP_RATIO:
            print(f"SKIP {c.address[:10]} LST-only ratio={lst_ratio:.2f}")
            dropped += 1
            continue

        diversity = len(non_lst_mints)
        print(f"OK   {c.address[:10]} diversity={diversity} lst_ratio={lst_ratio:.2f}")
        result.append(replace(c, token_diversity=diversity))

    print(f"[birdeye-sol] enrich: {len(candidates)} → {len(result)} (dropped LST-only: {dropped}, insufficient: {insufficient})")
    return result


def load_dune_csv(csv_path: str, ts: str) -> list[dict]:
    dst = os.path.join("data", "raw", "dune-csv-eth", f"{ts}.csv")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(csv_path, dst)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[dune-csv-eth] loaded {len(rows)} rows from {csv_path}, cached → {dst}")
    return rows


def normalize_dune_csv(rows: list[dict]) -> list[Candidate]:
    result = []
    for row in rows:
        try:
            div_raw = row.get("token_diversity")
            result.append(Candidate(
                address=row["address"],
                chain="eth",
                win_rate=min(float(row.get("win_rate") or 0), 1.0),
                trade_count=int(float(row.get("trade_count") or 0)),
                funds_usd=float(row.get("funds_usd") or 0),
                token_diversity=int(float(div_raw)) if div_raw not in (None, "") else None,
                max_drawdown=float(row.get("max_drawdown") or 0) if row.get("max_drawdown") not in (None, "") else None,
                recent_win_rate=None,
                source="dune-csv-eth",
            ))
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[dune-csv-eth] normalize skip: {exc}")
    return result


def apply_blocklist(candidates: list[Candidate], chain: str) -> list[Candidate]:
    bl = BLOCKLIST_SOL if chain == "sol" else BLOCKLIST_ETH
    before = len(candidates)
    filtered = [c for c in candidates if c.address not in bl]
    dropped = before - len(filtered)
    if dropped:
        print(f"[{candidates[0].source if candidates else chain}] blocklist: {dropped} dropped")
    return filtered


def apply_filters(candidates: list[Candidate]) -> list[Candidate]:
    passed = []
    for c in candidates:
        if c.funds_usd <= 0:
            print(f"  SKIP {c.address[:10]}… funds_usd missing or zero")
            continue
        if c.funds_usd < MIN_FUNDS_USD:
            continue
        if c.win_rate < MIN_WIN_RATE:
            continue
        if c.trade_count < MIN_TRADE_COUNT:
            continue
        if c.token_diversity is None:
            print(f"  NOTE {c.address[:10]}… {c.source} lacks token_diversity, skipped diversity check")
        elif c.token_diversity < MIN_TOKEN_DIVERSITY:
            continue
        if c.max_drawdown is not None and c.max_drawdown > MAX_DRAWDOWN_IF_KNOWN:
            continue
        passed.append(c)
    return passed


def to_wallet_score(c: Candidate) -> WalletScore:
    if c.max_drawdown is None:
        dd = 0.40
        print(f"  ⚠ drawdown unknown for {c.address[:10]}…, saved as 0.40 sentinel")
    else:
        dd = c.max_drawdown

    recent_wr = c.recent_win_rate if c.recent_win_rate is not None else c.win_rate
    trust = classify_trust_level(c.win_rate, c.trade_count, dd)

    return WalletScore(
        address=c.address,
        chain=c.chain,  # type: ignore[arg-type]
        win_rate=c.win_rate,
        trade_count=c.trade_count,
        max_drawdown=dd,
        funds_usd=c.funds_usd,
        recent_win_rate=recent_wr,
        trust_level=trust,
        status="watch",
    )


def persist(repo: AddressesRepo, candidates: list[Candidate], dry_run: bool) -> int:
    saved = 0
    for c in candidates:
        score = to_wallet_score(c)
        if dry_run:
            print(f"  {c.address[:10]}… | win_rate={c.win_rate:.2f} trades={c.trade_count} funds=${c.funds_usd:,.0f} trust={score.trust_level} status=watch")
            saved += 1
            continue
        existing = repo.get_wallet(c.address)
        if existing and existing.status in ("active", "retired"):
            print(f"  SKIP {c.address[:10]}… already {existing.status}")
            continue
        repo.upsert_wallet(score)
        saved += 1
    return saved


def _run_source(source: str, args: argparse.Namespace, ts: str, repo: AddressesRepo) -> int:
    """Fetch, normalize, filter, and persist one source. Returns saved count."""
    try:
        if source == "gmgn-sol":
            raw = fetch_gmgn_sol(args.limit, ts)
            candidates = normalize_gmgn_sol(raw)
            chain = "sol"
        elif source in ("birdeye-sol", "birdeye-sol-active"):
            if source == "birdeye-sol-active":
                # Second page (offset=10): surfaces more active traders vs liquid stakers
                raw = fetch_birdeye_sol(args.limit, ts, offset=10)
            else:
                raw = fetch_birdeye_sol(args.limit, ts)
            candidates = normalize_birdeye_sol(raw)
            if not getattr(args, "skip_enrich", False):
                with _http_client() as client:
                    candidates = enrich_birdeye_sol_diversity(candidates, client)
            chain = "sol"
        elif source == "dune-csv-eth":
            raw = load_dune_csv(args.csv, ts)
            candidates = normalize_dune_csv(raw)
            chain = "eth"
        else:
            raise ValueError(f"unknown source: {source}")
    except FetchError as exc:
        print(f"[{source}] fetch error: {exc}")
        raise

    candidates = apply_blocklist(candidates, chain)
    filtered = apply_filters(candidates)
    print(f"[{source}] filters: {len(filtered)} passed / {len(candidates)} evaluated")

    saved = persist(repo, filtered, dry_run=args.dry_run)
    tag = "(dry-run)" if args.dry_run else "written"
    print(f"[{source}] {tag}: {saved} wallets (status=watch)")
    return saved


def main(args: argparse.Namespace) -> None:
    ts = _utc_now_ts()
    repo = AddressesRepo(args.db)
    source = args.source
    total = 0

    if source in ("gmgn-sol", "birdeye-sol", "birdeye-sol-active", "dune-csv-eth"):
        if source == "dune-csv-eth" and not args.csv:
            print("[discover] --csv required for dune-csv-eth")
            sys.exit(1)
        try:
            total = _run_source(source, args, ts, repo)
        except FetchError as exc:
            print(f"[discover] ✗ {exc}")
            sys.exit(1)

    elif source == "all":
        gmgn_failed = False
        try:
            total += _run_source("gmgn-sol", args, ts, repo)
        except FetchError as exc:
            print(f"[discover] GMGN failed ({exc}), will fallback to Birdeye")
            gmgn_failed = True

        if args.csv:
            total += _run_source("dune-csv-eth", args, ts, repo)

        if gmgn_failed:
            for birdeye_src in ("birdeye-sol", "birdeye-sol-active"):
                try:
                    total += _run_source(birdeye_src, args, ts, repo)
                except FetchError as exc:
                    print(f"[discover] {birdeye_src} failed: {exc}")

        print("TODO: BSC support not yet implemented")

    else:
        print(f"[discover] Unknown --source '{source}'. Use gmgn-sol / birdeye-sol / birdeye-sol-active / dune-csv-eth / all")
        sys.exit(1)

    tag = "(dry-run)" if args.dry_run else ""
    print(f"Summary: {total} new watch-list wallets across source={source} {tag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage-1 wallet discovery")
    parser.add_argument("--source", default="gmgn-sol", help="gmgn-sol / birdeye-sol / dune-csv-eth / all")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--csv", default=None, help="Path to Dune ETH CSV (required for dune-csv-eth)")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-enrich", action="store_true",
                        help="Skip LST diversity enrichment (for debug/replay)")
    main(parser.parse_args())
