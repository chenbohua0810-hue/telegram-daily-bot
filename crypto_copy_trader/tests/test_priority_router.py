from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from models import OnChainEvent
from models import WalletScore
from signals.router import PriorityDecision, assign_priority


def build_event(amount_usd: float = 1_000.0, token_symbol: str = "ETH") -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc",
        tx_hash="0xtx",
        block_time=datetime(2026, 4, 22, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol=token_symbol,
        amount_token=Decimal("1"),
        amount_usd=Decimal(str(amount_usd)),
        raw={},
        token_address="",
    )


def build_wallet(
    trust_level: str = "medium",
    recent_win_rate: float = 0.55,
    status: str = "active",
) -> WalletScore:
    return WalletScore(
        address="0xabc",
        chain="eth",
        win_rate=0.6,
        trade_count=30,
        max_drawdown=0.3,
        funds_usd=50_000.0,
        recent_win_rate=recent_win_rate,
        trust_level=trust_level,
        status=status,
    )


THRESHOLDS = dict(
    high_value_usd=50_000.0,
    p1_min_usd=20_000.0,
    p1_min_win_rate=0.60,
)

KNOWN_TOKENS: set[str] = {"ETH", "BTC", "BNB"}


# ── P0 ───────────────────────────────────────────────────────────────────────

class TestP0:
    def test_exactly_at_high_value_threshold_is_p0(self) -> None:
        result = assign_priority(
            build_event(amount_usd=50_000.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P0"

    def test_above_high_value_threshold_is_p0(self) -> None:
        result = assign_priority(
            build_event(amount_usd=100_000.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P0"

    def test_unknown_token_triggers_p0(self) -> None:
        result = assign_priority(
            build_event(amount_usd=1_000.0, token_symbol="NEWCOIN"), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P0"

    def test_high_value_and_unknown_token_is_p0(self) -> None:
        result = assign_priority(
            build_event(amount_usd=100_000.0, token_symbol="NEWCOIN"), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P0"

    def test_p0_reason_not_empty(self) -> None:
        result = assign_priority(
            build_event(amount_usd=60_000.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P0"
        assert result.reason != ""


# ── P1 ───────────────────────────────────────────────────────────────────────

class TestP1:
    def test_high_trust_above_p1_threshold_is_p1(self) -> None:
        result = assign_priority(
            build_event(amount_usd=25_000.0),
            build_wallet(trust_level="high", recent_win_rate=0.70),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P1"

    def test_exactly_at_p1_thresholds_is_p1(self) -> None:
        result = assign_priority(
            build_event(amount_usd=20_000.0),
            build_wallet(trust_level="high", recent_win_rate=0.60),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P1"

    def test_high_trust_below_amount_not_p1(self) -> None:
        result = assign_priority(
            build_event(amount_usd=19_999.0),
            build_wallet(trust_level="high", recent_win_rate=0.70),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P2"

    def test_high_trust_low_win_rate_not_p1(self) -> None:
        result = assign_priority(
            build_event(amount_usd=25_000.0),
            build_wallet(trust_level="high", recent_win_rate=0.59),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P2"

    def test_medium_trust_not_p1(self) -> None:
        result = assign_priority(
            build_event(amount_usd=25_000.0),
            build_wallet(trust_level="medium", recent_win_rate=0.70),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P2"

    def test_p1_reason_not_empty(self) -> None:
        result = assign_priority(
            build_event(amount_usd=25_000.0),
            build_wallet(trust_level="high", recent_win_rate=0.70),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.reason != ""


# ── P3 ───────────────────────────────────────────────────────────────────────

class TestP3:
    def test_quant_failed_is_p3(self) -> None:
        result = assign_priority(
            build_event(), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=False, **THRESHOLDS,
        )
        assert result.level == "P3"

    def test_p3_beats_high_value_event(self) -> None:
        # quant failure takes precedence over P0 amount check
        result = assign_priority(
            build_event(amount_usd=100_000.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=False, **THRESHOLDS,
        )
        assert result.level == "P3"

    def test_p3_beats_unknown_token(self) -> None:
        result = assign_priority(
            build_event(token_symbol="NEWCOIN"), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=False, **THRESHOLDS,
        )
        assert result.level == "P3"

    def test_p3_beats_p1_conditions(self) -> None:
        result = assign_priority(
            build_event(amount_usd=25_000.0),
            build_wallet(trust_level="high", recent_win_rate=0.70),
            known_tokens=KNOWN_TOKENS, quant_passed=False, **THRESHOLDS,
        )
        assert result.level == "P3"

    def test_p3_reason_not_empty(self) -> None:
        result = assign_priority(
            build_event(), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=False, **THRESHOLDS,
        )
        assert result.reason != ""


# ── P2 ───────────────────────────────────────────────────────────────────────

class TestP2:
    def test_normal_event_is_p2(self) -> None:
        result = assign_priority(
            build_event(amount_usd=5_000.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P2"

    def test_just_below_p0_threshold_is_p2(self) -> None:
        result = assign_priority(
            build_event(amount_usd=49_999.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.level == "P2"

    def test_p2_reason_not_empty(self) -> None:
        result = assign_priority(
            build_event(amount_usd=5_000.0), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert result.reason != ""


# ── PriorityDecision type ─────────────────────────────────────────────────────

class TestPriorityDecisionType:
    def test_returns_priority_decision_instance(self) -> None:
        result = assign_priority(
            build_event(), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        assert isinstance(result, PriorityDecision)

    def test_is_frozen(self) -> None:
        result = assign_priority(
            build_event(), build_wallet(),
            known_tokens=KNOWN_TOKENS, quant_passed=True, **THRESHOLDS,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.level = "P0"  # type: ignore[misc]
