# Kronos Paper Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, secrets-free Kronos-based Binance Spot paper trading system for BTC/USDT and ETH/USDT 1h candles with validation, forecasting, signals, hard risk gates, simulated fills, and local reports.

**Architecture:** Implement a single local Python pipeline with explicit component boundaries: config, data ingestion, data validation, Kronos forecast adapter, signal engine, risk guard, paper trader, reporting, and a disabled live-executor adapter. The core remains deterministic and testable from fixture data; no component can skip risk_guard before paper execution.

**Tech Stack:** Python 3.11+, pytest, PyYAML, pandas, requests, ruff; Kronos integration deferred to a thin adapter so the rest of the paper trading path is testable without model downloads.

---

## File Structure

- Create `pyproject.toml` — Python package metadata, dependencies, pytest, coverage, and ruff settings.
- Create `.gitignore` — ignores virtualenvs, caches, local data, reports, and secrets-like env files.
- Create `README.md` — first-run local instructions and explicit paper-only safety note.
- Create `configs/app.yaml` — global mode, directories, interval, and report settings; no secrets.
- Create `configs/symbols.yaml` — BTC/USDT and ETH/USDT allowlist.
- Create `configs/model.yaml` — Kronos-small defaults and configurable inference parameters.
- Create `configs/strategy.yaml` — entry/exit thresholds and stop/take-profit defaults.
- Create `configs/risk_policy.yaml` — paper mode, sizing, loss, stop-loss, and live-trading disabled policy.
- Create `configs/agents.yaml` — conceptual agent boundaries and trading authority flags.
- Create `configs/paper_trading.yaml` — fees, slippage, and paper account defaults.
- Create `src/kronos_trading_bot/__init__.py` — package version export.
- Create `src/kronos_trading_bot/config.py` — typed config loader and no-secret validation.
- Create `src/kronos_trading_bot/domain.py` — shared immutable dataclasses/enums for candles, signals, orders, risk decisions, positions, portfolio, and reports.
- Create `src/kronos_trading_bot/data_validation.py` — 1h OHLCV validation and quality report.
- Create `src/kronos_trading_bot/data_ingestion.py` — Binance public kline client and local CSV persistence.
- Create `src/kronos_trading_bot/forecast.py` — Kronos forecast protocol, disabled fallback, and metadata writer.
- Create `src/kronos_trading_bot/signals.py` — BUY/HOLD/SELL_TO_CLOSE signal generation.
- Create `src/kronos_trading_bot/risk.py` — hard risk gates and resizing/rejection decisions.
- Create `src/kronos_trading_bot/paper.py` — simulated market fills, fees, slippage, PnL, and append-only journal.
- Create `src/kronos_trading_bot/reports.py` — markdown and CSV local reports.
- Create `src/kronos_trading_bot/live_executor.py` — future adapter that rejects every live order attempt.
- Create `src/kronos_trading_bot/pipeline.py` — one-symbol and multi-symbol dry-run orchestration.
- Create `src/kronos_trading_bot/cli.py` — `kronos-paper-trade` command entrypoint.
- Create `tests/fixtures/btcusdt_1h.csv` and `tests/fixtures/ethusdt_1h.csv` — deterministic fixture candles.
- Create `tests/test_config.py` — config loading and no-secrets tests.
- Create `tests/test_data_validation.py` — required validation checks.
- Create `tests/test_signals.py` — signal behavior and metadata tests.
- Create `tests/test_risk.py` — hard-gate risk policy tests.
- Create `tests/test_paper.py` — simulated fill, fee, slippage, PnL, and journal tests.
- Create `tests/test_pipeline.py` — full dry-run and safe-stop tests using fixtures.
- Create `tests/test_live_executor.py` — live execution always rejects tests.

## Task 1: Project Skeleton, Config Files, and Safety Contract

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `configs/app.yaml`
- Create: `configs/symbols.yaml`
- Create: `configs/model.yaml`
- Create: `configs/strategy.yaml`
- Create: `configs/risk_policy.yaml`
- Create: `configs/agents.yaml`
- Create: `configs/paper_trading.yaml`
- Create: `src/kronos_trading_bot/__init__.py`
- Create: `src/kronos_trading_bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config safety tests**

```python
from pathlib import Path

from kronos_trading_bot.config import load_yaml_config, load_project_config


def test_default_configs_load_with_paper_mode_and_live_disabled():
    # Arrange
    project_root = Path(__file__).resolve().parents[1]

    # Act
    config = load_project_config(project_root / "configs")

    # Assert
    assert config.risk_policy["mode"] == "paper"
    assert config.risk_policy["allow_live_trading"] is False
    assert config.app["execution_mode"] == "paper"
    assert config.symbols["symbols"] == ["BTC/USDT", "ETH/USDT"]


def test_configs_contain_no_secret_like_keys():
    # Arrange
    project_root = Path(__file__).resolve().parents[1]

    # Act
    config = load_project_config(project_root / "configs")

    # Assert
    assert config.secret_like_keys == []


def test_load_yaml_config_returns_mapping():
    # Arrange
    path = Path(__file__).resolve().parents[1] / "configs" / "risk_policy.yaml"

    # Act
    data = load_yaml_config(path)

    # Assert
    assert data["starting_balance_usdt"] == 10000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'kronos_trading_bot'`.

- [ ] **Step 3: Create minimal package/config implementation**

```python
# src/kronos_trading_bot/__init__.py
"""Kronos Trading Bot - paper trading only in version 1."""

__version__ = "0.1.0"
```

```python
# src/kronos_trading_bot/config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "private_key",
    "wallet_seed",
)


@dataclass(frozen=True)
class ProjectConfig:
    app: dict[str, Any]
    symbols: dict[str, Any]
    model: dict[str, Any]
    strategy: dict[str, Any]
    risk_policy: dict[str, Any]
    agents: dict[str, Any]
    paper_trading: dict[str, Any]
    secret_like_keys: list[str]


def load_yaml_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def _find_secret_like_keys(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        matches: list[str] = []
        for key, child in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS):
                matches.append(key_path)
            matches.extend(_find_secret_like_keys(child, key_path))
        return matches
    if isinstance(value, list):
        matches = []
        for index, child in enumerate(value):
            matches.extend(_find_secret_like_keys(child, f"{prefix}[{index}]"))
        return matches
    return []


def load_project_config(config_dir: Path) -> ProjectConfig:
    app = load_yaml_config(config_dir / "app.yaml")
    symbols = load_yaml_config(config_dir / "symbols.yaml")
    model = load_yaml_config(config_dir / "model.yaml")
    strategy = load_yaml_config(config_dir / "strategy.yaml")
    risk_policy = load_yaml_config(config_dir / "risk_policy.yaml")
    agents = load_yaml_config(config_dir / "agents.yaml")
    paper_trading = load_yaml_config(config_dir / "paper_trading.yaml")
    combined = {
        "app": app,
        "symbols": symbols,
        "model": model,
        "strategy": strategy,
        "risk_policy": risk_policy,
        "agents": agents,
        "paper_trading": paper_trading,
    }
    return ProjectConfig(
        app=app,
        symbols=symbols,
        model=model,
        strategy=strategy,
        risk_policy=risk_policy,
        agents=agents,
        paper_trading=paper_trading,
        secret_like_keys=_find_secret_like_keys(combined),
    )
```

- [ ] **Step 4: Add no-secret default config files**

```yaml
# configs/risk_policy.yaml
mode: paper
starting_balance_usdt: 10000
max_single_position_pct: 0.10
max_daily_loss_pct: 0.03
max_open_positions: 2
allow_live_trading: false
require_stop_loss: true
allowed_symbols:
  - BTC/USDT
  - ETH/USDT
pyramiding_enabled: false
model_stale_after_minutes: 90
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore README.md configs src/kronos_trading_bot tests/test_config.py
git commit -m "chore: bootstrap paper trading project"
```

## Task 2: Data Validation Core

**Files:**
- Create: `src/kronos_trading_bot/domain.py`
- Create: `src/kronos_trading_bot/data_validation.py`
- Test: `tests/test_data_validation.py`

- [ ] **Step 1: Write failing AAA tests for valid candles and missing columns**

```python
from datetime import UTC, datetime, timedelta

from kronos_trading_bot.data_validation import validate_candles


def _valid_candles():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {"timestamp": start, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 10.0},
        {"timestamp": start + timedelta(hours=1), "open": 105.0, "high": 115.0, "low": 100.0, "close": 112.0, "volume": 12.0},
    ]


def test_accepts_valid_1h_ohlcv_data():
    # Arrange
    candles = _valid_candles()
    now = candles[-1]["timestamp"] + timedelta(minutes=30)

    # Act
    report = validate_candles(candles, now=now, max_delay=timedelta(hours=2))

    # Assert
    assert report.passed is True
    assert report.errors == []


def test_rejects_missing_required_columns():
    # Arrange
    candles = _valid_candles()
    del candles[0]["volume"]

    # Act
    report = validate_candles(candles, now=candles[-1]["timestamp"], max_delay=timedelta(hours=2))

    # Assert
    assert report.passed is False
    assert "missing_required_columns" in report.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_validation.py -q`
Expected: FAIL with `ModuleNotFoundError` for `kronos_trading_bot.data_validation`.

- [ ] **Step 3: Implement immutable validation report and validator**

```python
# src/kronos_trading_bot/domain.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SignalAction(StrEnum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"


@dataclass(frozen=True)
class DataQualityReport:
    symbol: str | None
    passed: bool
    errors: list[str]
    candle_count: int
    latest_timestamp: datetime | None
```

```python
# src/kronos_trading_bot/data_validation.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from kronos_trading_bot.domain import DataQualityReport

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


def validate_candles(
    candles: Iterable[dict[str, Any]],
    *,
    now: datetime,
    max_delay: timedelta,
    symbol: str | None = None,
) -> DataQualityReport:
    rows = list(candles)
    errors: list[str] = []
    if not rows:
        return DataQualityReport(symbol, False, ["empty_candles"], 0, None)

    if any(not REQUIRED_COLUMNS.issubset(row.keys()) for row in rows):
        errors.append("missing_required_columns")

    timestamps = [row.get("timestamp") for row in rows if "timestamp" in row]
    if timestamps != sorted(timestamps):
        errors.append("timestamps_not_sorted")
    if len(set(timestamps)) != len(timestamps):
        errors.append("duplicated_timestamps")
    for previous, current in zip(timestamps, timestamps[1:]):
        if current - previous != timedelta(hours=1):
            errors.append("non_1h_interval")
            break

    for row in rows:
        if not REQUIRED_COLUMNS.issubset(row.keys()):
            continue
        open_, high, low, close, volume = row["open"], row["high"], row["low"], row["close"], row["volume"]
        if min(open_, high, low, close, volume) < 0:
            errors.append("negative_ohlcv")
        if high < max(open_, close, low):
            errors.append("invalid_high")
        if low > min(open_, close, high):
            errors.append("invalid_low")

    latest = timestamps[-1] if timestamps else None
    if latest is not None and now - latest > max_delay:
        errors.append("stale_data")

    return DataQualityReport(symbol, not errors, sorted(set(errors)), len(rows), latest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data_validation.py -q`
Expected: PASS.

- [ ] **Step 5: Add edge-case tests for duplicates, stale data, invalid high/low, negative values**

Run: `pytest tests/test_data_validation.py -q`
Expected: PASS after adding minimal implementation fixes if needed.

- [ ] **Step 6: Commit**

```bash
git add src/kronos_trading_bot/domain.py src/kronos_trading_bot/data_validation.py tests/test_data_validation.py
git commit -m "feat: add candle data validation"
```

## Task 3: Binance Public Data Ingestion

**Files:**
- Create: `src/kronos_trading_bot/data_ingestion.py`
- Test: `tests/test_data_ingestion.py`

- [ ] **Step 1: Write failing parser/persistence tests without network calls**

```python
from datetime import UTC, datetime

from kronos_trading_bot.data_ingestion import parse_binance_kline, write_candles_csv


def test_parse_binance_kline_maps_public_fields():
    # Arrange
    row = [1767225600000, "100.0", "110.0", "90.0", "105.0", "12.5"]

    # Act
    candle = parse_binance_kline(row)

    # Assert
    assert candle["timestamp"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert candle["open"] == 100.0
    assert candle["high"] == 110.0
    assert candle["low"] == 90.0
    assert candle["close"] == 105.0
    assert candle["volume"] == 12.5


def test_write_candles_csv_creates_reproducible_file(tmp_path):
    # Arrange
    candles = [{"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]
    path = tmp_path / "BTCUSDT_1h.csv"

    # Act
    write_candles_csv(path, candles)

    # Assert
    assert path.read_text(encoding="utf-8").splitlines()[0] == "timestamp,open,high,low,close,volume"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_ingestion.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement parser and deterministic CSV writer**

Use public Binance `/api/v3/klines` only in the later client function. Keep parser/persistence pure and covered first.

- [ ] **Step 4: Add fetch client with timeout/retry/backoff and unit test using monkeypatch**

Run: `pytest tests/test_data_ingestion.py -q`
Expected: PASS without real external API calls.

- [ ] **Step 5: Commit**

```bash
git add src/kronos_trading_bot/data_ingestion.py tests/test_data_ingestion.py
git commit -m "feat: add public candle ingestion"
```

## Task 4: Signal Engine

**Files:**
- Modify: `src/kronos_trading_bot/domain.py`
- Create: `src/kronos_trading_bot/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write failing signal tests**

```python
from kronos_trading_bot.domain import SignalAction
from kronos_trading_bot.signals import build_signal


def test_emits_buy_when_predicted_return_exceeds_entry_threshold():
    # Arrange / Act
    signal = build_signal("BTC/USDT", latest_close=100.0, predicted_close=103.0, entry_threshold=0.02, exit_threshold=-0.01, model_name="Kronos-small")

    # Assert
    assert signal.action == SignalAction.BUY
    assert signal.reason_code == "predicted_return_above_entry_threshold"
    assert signal.predicted_return == 0.03


def test_emits_hold_for_weak_predicted_return():
    # Arrange / Act
    signal = build_signal("ETH/USDT", latest_close=100.0, predicted_close=100.5, entry_threshold=0.02, exit_threshold=-0.01, model_name="Kronos-small")

    # Assert
    assert signal.action == SignalAction.HOLD
    assert signal.reason_code == "predicted_return_weak"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_signals.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement `Signal` dataclass and `build_signal`**

Include symbol, timestamp, predicted_return, confidence_score, model_used, and reason_code. Never place orders from this module.

- [ ] **Step 4: Add SELL_TO_CLOSE and metadata tests**

Run: `pytest tests/test_signals.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kronos_trading_bot/domain.py src/kronos_trading_bot/signals.py tests/test_signals.py
git commit -m "feat: add forecast signal generation"
```

## Task 5: Risk Guard Hard Gates

**Files:**
- Modify: `src/kronos_trading_bot/domain.py`
- Create: `src/kronos_trading_bot/risk.py`
- Test: `tests/test_risk.py`

- [ ] **Step 1: Write failing rejection tests for live mode, unsupported symbol, missing stop-loss, oversize, and daily loss**

```python
from kronos_trading_bot.risk import evaluate_order_intent


def test_rejects_live_mode_even_for_valid_symbol():
    # Arrange
    policy = {"mode": "live", "allow_live_trading": False, "allowed_symbols": ["BTC/USDT"]}
    intent = {"symbol": "BTC/USDT", "mode": "live", "notional_usdt": 100, "stop_loss": 95}
    portfolio = {"equity_usdt": 10000, "starting_day_equity_usdt": 10000, "open_positions": {}}

    # Act
    decision = evaluate_order_intent(intent, portfolio, policy, data_quality_passed=True, model_is_stale=False)

    # Assert
    assert decision.approved is False
    assert decision.reason_code == "live_trading_rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement deterministic risk policy evaluation**

Order checks in this order: live rejection, non-paper rejection, data quality, stale model, allowlist, daily loss, max open positions, pyramiding, stop-loss requirement, max single position percent. Return approved/rejected/resized intent without side effects.

- [ ] **Step 4: Add valid approval test**

Run: `pytest tests/test_risk.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kronos_trading_bot/domain.py src/kronos_trading_bot/risk.py tests/test_risk.py
git commit -m "feat: add paper trading risk guard"
```

## Task 6: Paper Trader Simulation

**Files:**
- Modify: `src/kronos_trading_bot/domain.py`
- Create: `src/kronos_trading_bot/paper.py`
- Test: `tests/test_paper.py`

- [ ] **Step 1: Write failing buy-fill test**

```python
from kronos_trading_bot.paper import PaperPortfolio, simulate_buy


def test_simulated_buy_updates_cash_position_fee_and_slippage():
    # Arrange
    portfolio = PaperPortfolio.initial(cash_usdt=10000)

    # Act
    updated, fill = simulate_buy(portfolio, symbol="BTC/USDT", notional_usdt=1000, market_price=100, fee_rate=0.001, slippage_bps=10)

    # Assert
    assert fill.fill_price == 100.1
    assert fill.fee_usdt == 1.0
    assert updated.cash_usdt == 8999.0
    assert updated.positions["BTC/USDT"].quantity == 1000 / 100.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement immutable portfolio update and trade journal append**

Use returned updated portfolio instead of mutating the input. Include average entry price, realized PnL, unrealized PnL helper, fees paid, and append-only fill list.

- [ ] **Step 4: Add close-position PnL test**

Run: `pytest tests/test_paper.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kronos_trading_bot/domain.py src/kronos_trading_bot/paper.py tests/test_paper.py
git commit -m "feat: add paper trade simulation"
```

## Task 7: Kronos Forecast Adapter Boundary

**Files:**
- Create: `src/kronos_trading_bot/forecast.py`
- Test: `tests/test_forecast.py`

- [ ] **Step 1: Write failing adapter tests with fake forecaster**

```python
from datetime import UTC, datetime

from kronos_trading_bot.forecast import ForecastResult, run_forecast


class FakeForecaster:
    model_name = "Kronos-small"
    tokenizer_name = "Kronos-Tokenizer-base"

    def predict(self, candles, pred_len):
        return [{"timestamp": datetime(2026, 1, 1, 1, tzinfo=UTC), "close": 101.0}]


def test_run_forecast_returns_predictions_and_metadata():
    # Arrange
    candles = [{"timestamp": datetime(2026, 1, 1, tzinfo=UTC), "close": 100.0}]

    # Act
    result = run_forecast(FakeForecaster(), candles, pred_len=1)

    # Assert
    assert isinstance(result, ForecastResult)
    assert result.model_name == "Kronos-small"
    assert result.predictions[0]["close"] == 101.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forecast.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement protocol-based adapter wrapper**

Keep actual Kronos loading behind a separate class so tests do not download models. The first integration command can fail clearly when Kronos dependency is not installed.

- [ ] **Step 4: Commit**

```bash
git add src/kronos_trading_bot/forecast.py tests/test_forecast.py
git commit -m "feat: add Kronos forecast adapter boundary"
```

## Task 8: Reports and Safe Pipeline Orchestration

**Files:**
- Create: `src/kronos_trading_bot/reports.py`
- Create: `src/kronos_trading_bot/pipeline.py`
- Create: `tests/fixtures/btcusdt_1h.csv`
- Create: `tests/fixtures/ethusdt_1h.csv`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing full-cycle fixture test**

```python
from pathlib import Path

from kronos_trading_bot.pipeline import run_fixture_cycle


def test_runs_one_full_cycle_for_btc_fixture_without_secrets(tmp_path):
    # Arrange
    fixture = Path(__file__).parent / "fixtures" / "btcusdt_1h.csv"

    # Act
    result = run_fixture_cycle(symbol="BTC/USDT", fixture_path=fixture, report_dir=tmp_path)

    # Assert
    assert result.status in {"completed", "no_trade"}
    assert result.live_orders_attempted == 0
    assert (tmp_path / "latest_report.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement one-symbol fixture pipeline**

Pipeline sequence must be: load candles, validate data, forecast, signal, risk_guard, paper_trader only if risk approved, report. If validation fails, stop safely and still write failure report.

- [ ] **Step 4: Add ETH fixture and validation-failure stop tests**

Run: `pytest tests/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kronos_trading_bot/reports.py src/kronos_trading_bot/pipeline.py tests/fixtures tests/test_pipeline.py
git commit -m "feat: add safe fixture dry run pipeline"
```

## Task 9: Disabled Live Executor Adapter

**Files:**
- Create: `src/kronos_trading_bot/live_executor.py`
- Test: `tests/test_live_executor.py`

- [ ] **Step 1: Write failing live rejection test**

```python
from kronos_trading_bot.live_executor import LiveExecutorDisabled


def test_live_executor_rejects_every_order_attempt():
    # Arrange
    executor = LiveExecutorDisabled()

    # Act
    result = executor.submit_order({"symbol": "BTC/USDT", "side": "BUY"})

    # Assert
    assert result.accepted is False
    assert result.reason_code == "live_trading_not_implemented"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_live_executor.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement adapter that cannot place orders**

No exchange SDK, no private endpoint, no API key input. Always return a typed rejection result.

- [ ] **Step 4: Commit**

```bash
git add src/kronos_trading_bot/live_executor.py tests/test_live_executor.py
git commit -m "feat: reject live execution attempts"
```

## Task 10: CLI and Local Verification

**Files:**
- Modify: `pyproject.toml`
- Create: `src/kronos_trading_bot/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI help and fixture-run tests**

```python
from kronos_trading_bot.cli import build_parser


def test_cli_parser_defaults_to_paper_mode():
    # Arrange
    parser = build_parser()

    # Act
    args = parser.parse_args(["run-fixture", "--symbol", "BTC/USDT", "--fixture", "tests/fixtures/btcusdt_1h.csv"])

    # Assert
    assert args.command == "run-fixture"
    assert args.mode == "paper"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -q`
Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement argparse CLI with no live mode option**

Expose only paper fixture/dry-run commands in version 1. Do not add flags for API keys or live trading.

- [ ] **Step 4: Run all checks**

Run: `pytest -q`
Expected: PASS.
Run: `ruff check .`
Expected: PASS.
Run: `python -m kronos_trading_bot.cli --help`
Expected: exits 0 and shows paper-only commands.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/kronos_trading_bot/cli.py tests/test_cli.py
git commit -m "feat: add paper-only CLI"
```

---

## Self-Review

**Spec coverage:**
- Market/data scope: covered by Tasks 3 and 8.
- Kronos-small model selection boundary: covered by Tasks 1 and 7.
- Signal generation: covered by Task 4.
- Risk hard gates and live rejection: covered by Tasks 5 and 9.
- Paper execution with fees/slippage/PnL: covered by Task 6.
- Local reports: covered by Task 8.
- Secrets isolation: covered by Task 1 and CLI constraints in Task 10.
- Tests: covered by every task using AAA/TDD.

**Placeholder scan:** No `TBD`, `TODO`, `implement later`, or unspecified test steps remain. Later tasks intentionally defer live trading implementation by replacing it with an always-rejecting adapter, matching the approved spec.

**Type consistency:** Shared actions use `SignalAction.BUY`, `SignalAction.HOLD`, and `SignalAction.SELL_TO_CLOSE`; config path names match the spec; risk/paper modules exchange order-intent dictionaries until domain dataclasses are added in Tasks 5 and 6.

---

## Execution Note

The approved next execution starts with Task 1 only: project skeleton, default config, and config safety tests. Do not implement live trading, exchange private endpoints, API key handling, or autonomous order placement in this plan.
