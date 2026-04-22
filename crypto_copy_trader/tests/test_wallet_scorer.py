from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from models.signals import WalletScore
from storage.addresses_repo import AddressesRepo
from storage.trades_repo import TradesRepo
from wallet_scorer.scorer import WalletScorer


def build_wallet(
    *,
    address: str = "0xabc123",
    win_rate: float = 0.62,
    trade_count: int = 60,
    max_drawdown: float = 0.20,
    funds_usd: float = 120000.0,
    recent_win_rate: float = 0.64,
    trust_level: str = "medium",
    status: str = "active",
) -> WalletScore:
    return WalletScore(
        address=address,
        chain="eth",
        win_rate=win_rate,
        trade_count=trade_count,
        max_drawdown=max_drawdown,
        funds_usd=funds_usd,
        recent_win_rate=recent_win_rate,
        trust_level=trust_level,
        status=status,
    )


def build_anthropic_client(reasoning: str = "維持追蹤，近期表現穩定。") -> SimpleNamespace:
    message = SimpleNamespace(content=[SimpleNamespace(text=reasoning)])
    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=message)))


@pytest.mark.asyncio
async def test_evaluate_retires_on_max_drawdown() -> None:
    scorer = WalletScorer(
        addresses_repo=Mock(),
        trades_repo=Mock(),
        anthropic_client=build_anthropic_client(),
        model="claude-3-5-haiku-latest",
    )

    result = await scorer.evaluate_wallet(
        build_wallet(max_drawdown=0.45),
        recent_performance={"trades": 12, "win_rate": 0.58},
    )

    assert result.decision == "retire"
    assert result.new_score.status == "retired"
    assert result.new_score.trust_level == "low"


@pytest.mark.asyncio
async def test_evaluate_watches_on_3_consecutive_losses() -> None:
    scorer = WalletScorer(
        addresses_repo=Mock(),
        trades_repo=Mock(),
        anthropic_client=build_anthropic_client(),
        model="claude-3-5-haiku-latest",
    )

    result = await scorer.evaluate_wallet(
        build_wallet(),
        recent_performance={"trades": 8, "win_rate": 0.55, "consecutive_losses": 3},
    )

    assert result.decision == "watch"
    assert result.new_score.status == "watch"
    assert result.new_score.trust_level == "low"


@pytest.mark.asyncio
async def test_evaluate_keeps_healthy_wallet() -> None:
    scorer = WalletScorer(
        addresses_repo=Mock(),
        trades_repo=Mock(),
        anthropic_client=build_anthropic_client(),
        model="claude-3-5-haiku-latest",
    )

    result = await scorer.evaluate_wallet(
        build_wallet(win_rate=0.61, recent_win_rate=0.72, max_drawdown=0.18),
        recent_performance={"trades": 18, "win_rate": 0.74},
    )

    assert result.decision == "keep"
    assert result.new_score.status == "active"
    assert result.new_score.trust_level == "high"


@pytest.mark.asyncio
async def test_evaluate_all_persists_history(tmp_path) -> None:
    addresses_repo = AddressesRepo(str(tmp_path / "addresses.db"))
    trades_repo = TradesRepo(str(tmp_path / "trades.db"))
    addresses_repo.upsert_wallet(build_wallet(address="0xactive", status="active"))
    addresses_repo.upsert_wallet(build_wallet(address="0xwatch", status="watch"))
    addresses_repo.upsert_wallet(build_wallet(address="0xretired", status="retired"))
    append_history = Mock(wraps=addresses_repo.append_history)
    addresses_repo.append_history = append_history

    scorer = WalletScorer(
        addresses_repo=addresses_repo,
        trades_repo=trades_repo,
        anthropic_client=build_anthropic_client(),
        model="claude-3-5-haiku-latest",
    )

    results = await scorer.evaluate_all()
    active_history = addresses_repo.get_history("0xactive", limit=5)
    watch_history = addresses_repo.get_history("0xwatch", limit=5)
    retired_history = addresses_repo.get_history("0xretired", limit=5)

    assert len(results) == 2
    assert append_history.call_count == 2
    assert len(active_history) == 1
    assert len(watch_history) == 1
    assert retired_history == []


@pytest.mark.asyncio
async def test_evaluate_llm_failure_falls_back_template_reasoning() -> None:
    anthropic_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
    )
    scorer = WalletScorer(
        addresses_repo=Mock(),
        trades_repo=Mock(),
        anthropic_client=anthropic_client,
        model="claude-3-5-haiku-latest",
    )

    result = await scorer.evaluate_wallet(
        build_wallet(),
        recent_performance={"trades": 6, "win_rate": 0.60},
    )

    assert result.decision == "keep"
    assert result.reasoning == "自動規則：keep"
