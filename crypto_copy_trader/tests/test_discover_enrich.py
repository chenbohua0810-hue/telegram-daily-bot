"""Tests for enrich_birdeye_sol_diversity in discover_wallets.py.

All tests mock _fetch_with_retry to avoid hitting the real Birdeye API.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from unittest.mock import MagicMock, patch

import pytest

import discover_wallets
from discover_wallets import (
    Candidate,
    FetchError,
    enrich_birdeye_sol_diversity,
    fetch_birdeye_sol,
    normalize_birdeye_sol,
)

# ── fixture mint addresses ─────────────────────────────────────────────────────
MSOL    = "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"
JITOSOL = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
WSOL    = "So11111111111111111111111111111111111111112"
USDC    = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_A = "TokenAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "TokenBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
TOKEN_C = "TokenCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
TOKEN_D = "TokenDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
TOKEN_E = "TokenEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"


# ── helpers ────────────────────────────────────────────────────────────────────

def _candidate(address: str = "Addr1234567890111") -> Candidate:
    return Candidate(
        address=address,
        chain="sol",
        win_rate=0.6,
        trade_count=100,
        funds_usd=50_000.0,
        token_diversity=None,
        max_drawdown=None,
        recent_win_rate=None,
        source="birdeye-sol",
    )


def _tx(base_mint: str, quote_mint: str) -> dict:
    return {
        "block_unix_time": 1_714_000_000,
        "base":  {"address": base_mint,  "ui_amount": 1.0, "price": 100.0},
        "quote": {"address": quote_mint, "ui_amount": 1.0, "price": 100.0},
    }


def _resp(items: list[dict]) -> dict:
    return {"data": {"items": items}}


# ── tests ──────────────────────────────────────────────────────────────────────


def test_lst_only_wallet_dropped():
    """Wallet whose txs are all SOL↔mSOL or SOL↔jitoSOL must be dropped."""
    txs = [_tx(WSOL, MSOL)] * 6 + [_tx(WSOL, JITOSOL)] * 4   # 10 txs, ratio=1.0
    candidate = _candidate()

    with patch.object(discover_wallets, "_fetch_with_retry", return_value=_resp(txs)):
        result = enrich_birdeye_sol_diversity([candidate], MagicMock())

    assert result == []


def test_mixed_trader_kept_with_diversity():
    """Wallet with 5 unique non-LST tokens is kept and token_diversity=5."""
    lst_txs = [_tx(WSOL, MSOL)] * 2
    diverse_txs = [
        _tx(WSOL, TOKEN_A),
        _tx(WSOL, TOKEN_B),
        _tx(WSOL, TOKEN_C),
        _tx(WSOL, TOKEN_D),
        _tx(WSOL, TOKEN_E),
    ]
    # Pad to 10 total; TOKEN_A already counted, diversity stays 5
    txs = lst_txs + diverse_txs + [_tx(WSOL, TOKEN_A)] * 3

    with patch.object(discover_wallets, "_fetch_with_retry", return_value=_resp(txs)):
        result = enrich_birdeye_sol_diversity([_candidate()], MagicMock())

    assert len(result) == 1
    assert result[0].token_diversity == 5


def test_insufficient_samples_keeps_candidate(capsys):
    """Only 3 txs returned → candidate kept, token_diversity=None, NOTE logged."""
    txs = [_tx(WSOL, MSOL)] * 3   # 3 < MIN_SAMPLED_TXS(10)
    candidate = _candidate()

    with patch.object(discover_wallets, "_fetch_with_retry", return_value=_resp(txs)):
        result = enrich_birdeye_sol_diversity([candidate], MagicMock())

    assert len(result) == 1
    assert result[0].token_diversity is None
    out = capsys.readouterr().out
    assert "NOTE" in out


def test_api_error_keeps_candidate(capsys):
    """FetchError during enrichment → candidate kept, WARN logged, no crash."""
    candidate = _candidate()

    with patch.object(
        discover_wallets, "_fetch_with_retry", side_effect=FetchError("503 timeout")
    ):
        result = enrich_birdeye_sol_diversity([candidate], MagicMock())

    assert len(result) == 1
    assert result[0].token_diversity is None
    out = capsys.readouterr().out
    assert "WARN" in out


def test_wsol_counted_as_sol_not_diversity():
    """wSOL↔USDC: USDC counted as diversity (1), wSOL not counted."""
    txs = [_tx(WSOL, USDC)] * 10   # lst_ratio=0, non-LST={USDC}

    with patch.object(discover_wallets, "_fetch_with_retry", return_value=_resp(txs)):
        result = enrich_birdeye_sol_diversity([_candidate()], MagicMock())

    assert len(result) == 1
    assert result[0].token_diversity == 1


def test_immutability_candidate_not_mutated():
    """enrich returns new Candidate objects; original list objects are unchanged."""
    txs = [_tx(WSOL, USDC)] * 10
    original = _candidate()
    original_diversity = original.token_diversity   # None

    with patch.object(discover_wallets, "_fetch_with_retry", return_value=_resp(txs)):
        result = enrich_birdeye_sol_diversity([original], MagicMock())

    assert original.token_diversity is original_diversity   # still None
    assert result[0] is not original
    assert result[0].token_diversity == 1


# ── birdeye-sol-active: parameterized fetch ────────────────────────────────────

_BIRDEYE_ITEMS = [
    {"network": "solana", "address": "AAAA1234567890111", "pnl": 1000.0, "volume": 50000.0, "trade_count": 80},
    {"network": "solana", "address": "BBBB1234567890222", "pnl": 500.0,  "volume": 30000.0, "trade_count": 55},
]

def test_fetch_birdeye_sol_default_params():
    """Default call uses sort_by=PnL and time_frame=1W."""
    birdeye_resp = {"data": {"items": _BIRDEYE_ITEMS}}
    captured = {}

    def fake_fetch(client, url, params=None, extra_headers=None):
        captured.update(params or {})
        return birdeye_resp

    with patch.object(discover_wallets, "_fetch_with_retry", side_effect=fake_fetch):
        with patch("discover_wallets._cache_raw_json", return_value="dummy"):
            result = fetch_birdeye_sol(limit=2, ts="20260101-000000")

    assert captured.get("sort_by") == "PnL"
    assert captured.get("time_frame") == "1W"
    assert len(result) == 2


def test_fetch_birdeye_sol_active_params():
    """birdeye-sol-active uses offset=10 to fetch the second page of results."""
    birdeye_resp = {"data": {"items": _BIRDEYE_ITEMS}}
    captured = {}

    def fake_fetch(client, url, params=None, extra_headers=None):
        captured.update(params or {})
        return birdeye_resp

    with patch.object(discover_wallets, "_fetch_with_retry", side_effect=fake_fetch):
        with patch("discover_wallets._cache_raw_json", return_value="dummy"):
            result = fetch_birdeye_sol(limit=2, ts="20260101-000000", offset=10)

    assert captured.get("offset") == 10
    assert captured.get("sort_by") == "PnL"    # default
    assert captured.get("time_frame") == "1W"  # default
    assert len(result) == 2


def test_normalize_birdeye_sol_active_items():
    """normalize_birdeye_sol handles items that only have address/pnl/volume/trade_count."""
    result = normalize_birdeye_sol(_BIRDEYE_ITEMS)

    assert len(result) == 2
    assert result[0].address == "AAAA1234567890111"
    assert result[0].trade_count == 80
    assert result[0].chain == "sol"
    assert result[0].token_diversity is None   # Birdeye doesn't provide this
