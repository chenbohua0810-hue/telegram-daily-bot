from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import discover_wallets
from discover_wallets import Candidate
from main import PipelineDeps, process_event
from models import OnChainEvent, Portfolio, WalletScore
from reporting import TelegramCommandController, TradingControlState, build_daily_report
from signals.mev_detector import MevDetector, check_mev_event
from storage import AddressesRepo, TradesRepo


def make_wallet(address: str = "0xabc", *, status: str = "active", pnl: float = 0.0) -> WalletScore:
    return WalletScore(
        address=address,
        chain="eth",
        win_rate=0.7,
        trade_count=80,
        max_drawdown=0.15,
        funds_usd=100000.0,
        recent_win_rate=0.7,
        trust_level="high",
        status=status,
        binance_listable_pnl_180d=pnl,
    )


def make_event(wallet: str = "0xabc", *, tx_type: str = "swap_in", block_number: int = 1) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet=wallet,
        tx_hash=f"tx-{wallet}-{tx_type}-{block_number}",
        block_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        tx_type=tx_type,
        token_symbol="ETH",
        amount_token=Decimal("1"),
        amount_usd=Decimal("10000"),
        raw={"block_number": block_number},
        token_address="0xeth",
    )


def test_binance_listable_filter_keeps_only_profitable_listable_wallets(tmp_path) -> None:
    symbols_path = tmp_path / "binance_symbols.json"
    symbols_path.write_text(json.dumps(["ETH/USDT", "SOL/USDT"]), encoding="utf-8")
    candidates = [
        Candidate("0xkeep", "eth", 0.7, 80, 50000.0, 8, 0.2, None, "dune", "ETH/USDT", 35000.0, 0.1),
        Candidate("0xlow", "eth", 0.7, 80, 50000.0, 8, 0.2, None, "dune", "ETH/USDT", 29999.0, 0.1),
        Candidate("0xmissing", "eth", 0.7, 80, 50000.0, 8, 0.2, None, "dune", "DOGE/USDT", 60000.0, 0.1),
    ]

    filtered = discover_wallets.apply_binance_listable_filter(candidates, str(symbols_path))

    assert [candidate.address for candidate in filtered] == ["0xkeep"]


def test_sol_wallet_with_mostly_non_listable_meme_trades_is_dropped(tmp_path) -> None:
    symbols_path = tmp_path / "binance_symbols.json"
    symbols_path.write_text(json.dumps(["SOL/USDT"]), encoding="utf-8")
    candidates = [
        Candidate("sol-drop", "sol", 0.7, 80, 50000.0, 8, 0.2, None, "gmgn", "SOL/USDT", 50000.0, 0.81),
        Candidate("sol-keep", "sol", 0.7, 80, 50000.0, 8, 0.2, None, "gmgn", "SOL/USDT", 50000.0, 0.79),
    ]

    filtered = discover_wallets.apply_binance_listable_filter(candidates, str(symbols_path))

    assert [candidate.address for candidate in filtered] == ["sol-keep"]


def test_wallet_score_persists_binance_listable_pnl(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    repo.upsert_wallet(make_wallet(pnl=42000.0))

    stored = repo.get_wallet("0xabc")

    assert stored is not None
    assert stored.binance_listable_pnl_180d == pytest.approx(42000.0)


def test_weekly_refresh_demotes_and_retires_wallets(tmp_path) -> None:
    from refresh_wallets_weekly import CandidateRefresh, refresh_wallet_statuses

    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    repo.upsert_wallet(make_wallet("0xactive", status="active"))
    repo.upsert_wallet(make_wallet("0xwatch", status="watch"))

    summary = refresh_wallet_statuses(
        repo,
        performance_30d={
            "0xactive": {"pnl_usd": -1.0, "win_rate": 0.5},
            "0xwatch": {"pnl_usd": -2.0, "win_rate": 0.4},
        },
        top_candidates=[CandidateRefresh(address="0xnew", chain="eth", pnl_180d=50000.0, win_rate=0.7, trade_count=70)],
        prior_watch_failures={"0xwatch": 1},
        now=datetime(2026, 5, 3, tzinfo=timezone.utc),
    )

    assert summary.demoted == 1
    assert summary.retired == 1
    assert summary.promoted == 1
    assert repo.get_wallet("0xactive").status == "watch"
    assert repo.get_wallet("0xwatch").status == "retired"
    assert repo.get_wallet("0xnew").status == "watch"


def test_per_wallet_pnl_aggregation(tmp_path) -> None:
    repo = TradesRepo(str(tmp_path / "trades.db"))
    repo.record_trade(symbol="ETH/USDT", action="buy", quantity=Decimal("1"), price=Decimal("110"), fee_usdt=Decimal("0"), source_wallet="0xa", confidence=90, reasoning="ok", status="filled", paper_trading=False, pre_trade_mid_price=Decimal("100"))
    repo.record_trade(symbol="BTC/USDT", action="buy", quantity=Decimal("1"), price=Decimal("90"), fee_usdt=Decimal("0"), source_wallet="0xb", confidence=90, reasoning="ok", status="filled", paper_trading=False, pre_trade_mid_price=Decimal("100"))

    rows = repo.get_per_wallet_pnl(days=30)

    assert rows[0]["source_wallet"] == "0xa"
    assert rows[0]["pnl_usdt"] == pytest.approx(10.0)
    assert rows[1]["source_wallet"] == "0xb"
    assert rows[1]["pnl_usdt"] == pytest.approx(-10.0)


def test_daily_report_renders_correctly(tmp_path) -> None:
    repo = TradesRepo(str(tmp_path / "trades.db"))
    repo.set_daily_pnl("2026-05-01", Decimal("100"), Decimal("25"), Decimal("10000"))
    report = build_daily_report(
        date="2026-05-01",
        portfolio_value=Decimal("10125"),
        portfolio_delta_pct=0.0125,
        portfolio_7d_delta_pct=0.05,
        trades_repo=repo,
        health={"ws_uptime_pct": 99.0, "llm_fallback_rate": 0.01, "api_rate_limit_hits": 0},
    )

    assert "📊 Daily Report (2026-05-01)" in report
    assert "Portfolio: $10,125" in report
    assert "Realized PnL: $100" in report
    assert "Health: WS uptime 99.0%" in report


@pytest.mark.asyncio
async def test_pause_blocks_new_entries(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    addresses_repo = AddressesRepo(str(tmp_path / "addresses.db"))
    trades_repo = TradesRepo(str(tmp_path / "trades.db"))
    addresses_repo.upsert_wallet(make_wallet())
    deps = PipelineDeps(
        settings=SimpleNamespace(),
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        executor=SimpleNamespace(),
        anthropic=SimpleNamespace(),
        claude_backend=SimpleNamespace(),
        batch_scorer=SimpleNamespace(),
        notifier=SimpleNamespace(),
        trade_logger=SimpleNamespace(log_skip=Mock()),
        http=SimpleNamespace(),
        binance_symbols={"ETH/USDT"},
        recent_events_cache=[],
        btc_24h_vol_pct=0.0,
        correlation_provider=lambda *_: {},
        control_state=TradingControlState(is_paused=True),
    )

    await process_event(make_event(), Portfolio(Decimal("100"), {}, Decimal("100"), 0.0), 0.0, deps)

    deps.trade_logger.log_skip.assert_called_once()
    assert deps.trade_logger.log_skip.call_args.args[1] == "manual_pause"


@pytest.mark.asyncio
async def test_unauthorized_chat_id_ignored() -> None:
    state = TradingControlState()
    controller = TelegramCommandController(
        chat_id="123",
        control_state=state,
        executor=Mock(),
        trades_repo=Mock(),
        notifier=Mock(),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=999), message=SimpleNamespace(reply_text=AsyncMock()))

    await controller.handle_pause(update, SimpleNamespace(args=[]))

    assert state.is_paused is False
    update.message.reply_text.assert_not_awaited()


def test_mev_detector_flags_same_block_in_out() -> None:
    detector = MevDetector(blacklist=set())
    first = detector.check(make_event(tx_type="swap_in", block_number=42))
    second = detector.check(make_event(tx_type="swap_out", block_number=42))

    assert first.is_mev_suspect is False
    assert second.is_mev_suspect is True


def test_mev_detector_flags_blacklisted_wallet(tmp_path) -> None:
    blacklist_path = tmp_path / "mev_blacklist.json"
    blacklist_path.write_text(json.dumps({"entries": [{"address": "0xabc"}]}), encoding="utf-8")

    checked = check_mev_event(make_event(wallet="0xabc"), blacklist_path=str(blacklist_path))

    assert checked.is_mev_suspect is True


@pytest.mark.asyncio
async def test_wallet_scorer_retires_after_three_mev_suspicions() -> None:
    from wallet_scorer import WalletScorer

    scorer = WalletScorer(addresses_repo=Mock(), trades_repo=Mock(), anthropic_client=SimpleNamespace(messages=SimpleNamespace(create=AsyncMock())), model="model")

    result = await scorer.evaluate_wallet(make_wallet(), {"win_rate": 0.7, "mev_suspect_count": 3})

    assert result.decision == "retire"
    assert result.new_score.status == "retired"


def test_mev_blacklist_merge_preserves_high_confidence() -> None:
    from refresh_mev_blacklist import merge_blacklist_entries

    merged, stats = merge_blacklist_entries(
        {"entries": [{"address": "0xabc", "confidence": "high", "source": "manual"}]},
        [{"address": "0xabc", "confidence": "medium", "source": "dune", "label": "new"}],
        today="2026-05-01",
    )

    assert stats["added"] == 0
    assert stats["updated"] == 1
    assert merged["entries"][0]["confidence"] == "high"


def test_active_wallet_match_triggers_retire_decision(tmp_path) -> None:
    from refresh_mev_blacklist import retire_matching_active_wallets

    addresses = AddressesRepo(str(tmp_path / "addresses.db"))
    addresses.upsert_wallet(make_wallet("0xabc"))
    decisions_path = tmp_path / "wallet_decisions.jsonl"
    notifier = SimpleNamespace(notify_risk_alert=AsyncMock())

    count = asyncio.run(retire_matching_active_wallets(addresses, {"0xabc"}, str(decisions_path), notifier))

    assert count == 1
    assert addresses.get_wallet("0xabc").status == "retired"
    assert "0xabc" in decisions_path.read_text(encoding="utf-8")
    notifier.notify_risk_alert.assert_awaited_once()
