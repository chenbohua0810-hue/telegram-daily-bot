# Kronos Binance Spot Paper Trading System Design

Date: 2026-05-05
Status: Approved for specification; implementation not started
Owner: chenbohua
Primary machine target: MacBook Pro M4, 16GB memory

## 1. Purpose

This document defines the first complete design for a Kronos-based crypto market analysis and paper trading system.

The long-term goal is to evolve toward automated trading. The first version is deliberately limited to paper trading only. It must not place live orders, must not require exchange API secrets, and must preserve a clean safety boundary between analysis, simulated execution, and any future live execution layer.

The system should help answer these questions:

- Can Kronos produce useful BTC/USDT and ETH/USDT 1h signals?
- Do those signals survive realistic paper trading assumptions such as fees and slippage?
- Which model configuration is practical on a MacBook Pro M4 with 16GB memory?
- What safety gates are required before any future live trading mode is considered?

## 2. First-Version Scope

### 2.1 Market

- Exchange: Binance Spot
- Symbols:
  - BTC/USDT
  - ETH/USDT
- Interval: 1h candles
- Execution mode: paper trading only
- Data source: Binance public market data endpoints or downloaded public candle files
- Authentication: not required for first version

### 2.2 Model Usage

Default model:

- Kronos-small

Optional model roles:

- Kronos-mini: fast scan or low-resource mode
- Kronos-base: slower second-pass validation for high-confidence signals
- Kronos-large: out of scope because it is not publicly available and is not appropriate for the target MacBook first version

The first implementation should support model selection through configuration, but only Kronos-small is required for acceptance.

### 2.3 Paper Trading Baseline

- Starting paper balance: 10,000 USDT
- Maximum single position size: 10% of equity
- Maximum daily loss: 3% of starting day equity
- Maximum open positions: 2, one per configured symbol
- Trading direction: spot long-only for first version
- Margin, leverage, shorting, futures, options: out of scope

## 3. Non-Goals

The first version must not include:

- Live trading
- Futures or leverage
- Autonomous order placement
- API keys in source files or config files
- Fine-tuning Kronos on the MacBook
- Portfolio optimization beyond simple position sizing
- Social/news signal ingestion
- LLM-generated direct trade execution
- Any bypass around risk_guard

These can be revisited only after the paper trading system produces stable evidence.

## 4. Architectural Principles

1. Safety first: paper trading must be the default and only implemented execution mode in version 1.
2. Secrets isolation: no API key, token, wallet seed, or private credential is stored in repository files.
3. Deterministic core: market data, signals, risk decisions, and paper fills must be reproducible from logged inputs.
4. Explicit interfaces: each component has narrow inputs and outputs.
5. Agent boundaries are advisory in version 1: define agents in the spec, but implementable as a single local pipeline first.
6. Live execution is a future adapter, not part of the paper trading path.
7. Risk rules are hard gates, not suggestions from an LLM.
8. Mac-friendly execution: use Kronos-small first, keep batch sizes modest, and avoid fine-tuning in the first version.

## 5. System Components

### 5.1 data_ingestion

Responsibility:

- Fetch or load Binance Spot 1h OHLCV data for BTC/USDT and ETH/USDT.
- Store raw candle data locally in a reproducible format.
- Avoid using private endpoints in version 1.

Inputs:

- symbols
- interval
- start time
- end time
- data directory

Outputs:

- raw candle files
- ingestion metadata
- fetch status report

Failure handling:

- Retry transient network failures with backoff.
- Stop the pipeline if the latest required candle is unavailable.
- Mark missing or duplicated candles explicitly.

### 5.2 data_validation

Responsibility:

- Validate candle continuity and quality before forecasting.

Checks:

- Required columns exist: timestamp, open, high, low, close, volume
- Timestamps are sorted and unique
- Candle interval is 1h
- No missing recent candle inside the configured lookback window
- high >= max(open, close, low)
- low <= min(open, close, high)
- open, high, low, close, volume are non-negative
- Data freshness is within allowed delay

Outputs:

- validated candle frame
- data quality report
- pass/fail decision

If validation fails, no forecast or trade simulation should run for that symbol.

### 5.3 kronos_forecast

Responsibility:

- Load the configured Kronos tokenizer and model.
- Generate forecasts from validated OHLCV data.
- Save predictions and forecast metadata.

Default configuration:

- model: Kronos-small
- tokenizer: Kronos-Tokenizer-base
- lookback: 400 candles
- pred_len: configurable; first version default is 1 to 6 future 1h candles
- temperature: 1.0
- top_p: 0.9
- sample_count: 1 initially; configurable for later experiments

Outputs:

- prediction table with future timestamps
- forecast summary
- model metadata

MacBook M4 16GB guidance:

- Use inference only in version 1.
- Do not fine-tune in version 1.
- Prefer Kronos-small for the main run.
- Kronos-base may be slow but can be tested later as optional validation.

### 5.4 signal_engine

Responsibility:

- Convert Kronos forecasts into explicit trading signals.

Inputs:

- latest validated candle
- forecasted candles
- current paper portfolio state
- strategy configuration

Possible outputs:

- BUY
- HOLD
- SELL_TO_CLOSE

First-version signal logic:

- Spot long-only.
- BUY when predicted return exceeds configured threshold and data quality passes.
- HOLD when predicted return is weak or ambiguous.
- SELL_TO_CLOSE when predicted return is below exit threshold or stop-loss/take-profit is triggered.

Signal metadata:

- symbol
- timestamp
- predicted_return
- confidence score
- model used
- reason code

The signal_engine must not place orders. It only emits proposed actions.

### 5.5 risk_guard

Responsibility:

- Approve, reject, or resize proposed paper orders using hard-coded risk policy loaded from configuration.

First-version hard rules:

- Reject all live trading requests.
- Reject any order if mode is not paper.
- Reject if data validation failed.
- Reject if daily loss exceeds 3%.
- Reject if proposed position exceeds 10% of equity.
- Reject if symbol is not in the configured allowlist.
- Reject if stop-loss is missing for a new position.
- Reject if the same symbol already has an open position and pyramiding is disabled.
- Reject if model output is stale.

Outputs:

- approved_order_intent
- rejected_order_intent with reason
- resized_order_intent with reason

The risk_guard is the main safety boundary. No execution component, paper or live, should accept an order intent unless risk_guard has approved it.

### 5.6 paper_trader

Responsibility:

- Simulate order execution, position state, fees, slippage, and PnL.

Assumptions for first version:

- Market-order style simulated fills
- Configurable taker fee
- Configurable slippage basis points
- No partial fills in first version
- No exchange downtime simulation in first version

State tracked:

- cash balance
- open positions
- average entry price
- realized PnL
- unrealized PnL
- fees paid
- trade log
- daily equity curve

Outputs:

- paper portfolio state
- order simulation log
- trade journal
- performance metrics

### 5.7 report_monitor

Responsibility:

- Produce human-readable reports and operational alerts.

Reports:

- latest forecast summary
- latest signal summary
- risk approval/rejection summary
- open paper positions
- daily PnL
- cumulative equity curve
- drawdown
- win/loss count

First version can write local markdown/CSV reports. Telegram or other push notifications are optional future work and should not be required for the first implementation.

### 5.8 live_executor_future_adapter

Responsibility:

- Define a future interface for live trading without implementing live order placement in version 1.

Version 1 behavior:

- disabled by default
- rejects every live order attempt
- logs a clear reason: live trading not implemented or not enabled

Future requirements before enabling:

- API keys only through environment variables or a secret manager
- separate live_trading_enabled flag
- manual confirmation gate for initial live phase
- exchange order simulation or dry-run check
- independent spend limits
- circuit breakers
- complete audit log
- small dedicated exchange sub-account

## 6. Agent Design

The first implementation may run as a single pipeline. Agents are defined as conceptual boundaries and future orchestration units.

### 6.1 data_agent

Role:

- Fetch and validate Binance public market data.

Can trade:

- false

Outputs:

- clean OHLCV data
- data quality report

### 6.2 forecast_agent

Role:

- Run Kronos inference and save forecasts.

Can trade:

- false

Outputs:

- prediction files
- forecast summary

### 6.3 strategy_agent

Role:

- Convert model forecasts into proposed signals.

Can trade:

- false

Outputs:

- signal proposals
- confidence score
- rationale

### 6.4 risk_agent

Role:

- Enforce hard risk policy and approve or reject proposed order intents.

Can trade:

- false

Outputs:

- risk decision
- rejection reason
- approved paper order intent

### 6.5 paper_execution_agent

Role:

- Simulate execution only after risk approval.

Can trade:

- paper only

Outputs:

- simulated fill
- updated paper portfolio state

### 6.6 monitor_agent

Role:

- Generate reports, summarize status, and alert on errors.

Can trade:

- false

Outputs:

- markdown report
- CSV metrics
- error summaries

### 6.7 live_execution_agent

Role:

- Future live execution adapter.

Can trade:

- false in version 1

Version 1 status:

- disabled
- must reject all live order attempts

## 7. Data Flow

1. Scheduler or manual command starts a run.
2. data_ingestion fetches latest Binance Spot 1h candles.
3. data_validation checks data quality.
4. If validation fails, report_monitor records failure and the run stops for that symbol.
5. kronos_forecast generates forecasts for valid symbols.
6. signal_engine creates proposed signals.
7. risk_guard approves, rejects, or resizes proposed paper order intents.
8. paper_trader simulates approved paper orders.
9. report_monitor writes reports and metrics.
10. The run exits with a clear status.

No component should skip directly from forecast to execution.

## 8. Configuration Files To Create During Implementation

The implementation plan should create these files later:

- configs/app.yaml
- configs/symbols.yaml
- configs/model.yaml
- configs/strategy.yaml
- configs/risk_policy.yaml
- configs/agents.yaml
- configs/paper_trading.yaml

These files should contain no secrets.

### 8.1 Example risk policy shape

```yaml
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
```

### 8.2 Example model policy shape

```yaml
default_model: Kronos-small
fast_model: Kronos-mini
validation_model: Kronos-base
lookback: 400
pred_len: 6
temperature: 1.0
top_p: 0.9
sample_count: 1
```

## 9. Security and Safety Requirements

### 9.1 Secrets

- No API keys in repository files.
- No secrets in logs.
- No secrets in reports.
- Version 1 should not need Binance private API credentials.

### 9.2 Trading authority

- Version 1 has no live trading authority.
- live_executor_future_adapter must reject all live order attempts.
- Any future live mode requires explicit separate approval and a new design review.

### 9.3 Circuit breakers

Paper trading should simulate these circuit breakers from the start:

- stop new entries after daily loss exceeds 3%
- stop new entries after repeated data validation failures
- stop new entries after repeated model inference failures
- stop new entries if reports cannot be written

### 9.4 Audit logging

Every run should log:

- data source and timestamp
- model and tokenizer name
- signal inputs and outputs
- risk decisions
- paper fills
- portfolio state before and after the run
- errors and rejected actions

## 10. Testing Strategy

Use AAA style tests: Arrange, Act, Assert.

Required test categories:

### 10.1 Data validation tests

- accepts valid 1h OHLCV data
- rejects missing required columns
- rejects duplicated timestamps
- rejects stale data
- rejects invalid high/low relationships

### 10.2 Signal tests

- emits BUY when predicted return exceeds entry threshold
- emits HOLD for weak predicted return
- emits SELL_TO_CLOSE when exit threshold is hit
- includes reason codes and confidence metadata

### 10.3 Risk guard tests

- rejects live mode
- rejects oversize position
- rejects unsupported symbol
- rejects missing stop-loss
- rejects after daily loss limit
- approves valid paper order intent

### 10.4 Paper trader tests

- updates cash and position after simulated buy
- computes fees
- applies slippage
- closes position and records realized PnL
- maintains an append-only trade journal

### 10.5 End-to-end dry-run tests

- runs one full cycle for BTC/USDT with fixture data
- runs one full cycle for ETH/USDT with fixture data
- stops safely when data validation fails
- writes reports without requiring secrets

## 11. Acceptance Criteria

The first implementation is acceptable when:

1. It can run locally on the MacBook Pro M4 16GB without requiring fine-tuning.
2. It can fetch or load BTC/USDT and ETH/USDT 1h candles.
3. It validates data before inference.
4. It runs Kronos-small inference for both symbols.
5. It produces explicit BUY/HOLD/SELL_TO_CLOSE signals.
6. It applies risk_guard before simulated execution.
7. It simulates paper trades with fees and slippage.
8. It writes local reports and trade logs.
9. It contains no API keys or secrets.
10. It has tests for validation, signal generation, risk policy, and paper trading.
11. Live execution is disabled and cannot be accidentally triggered.

## 12. Implementation Phases

### Phase 0: Project skeleton and configuration

- Create project structure.
- Add config files.
- Add no-secret policy.
- Add fixture data for tests.

### Phase 1: Data ingestion and validation

- Fetch Binance public 1h candles.
- Store raw and validated data.
- Add validation tests.

### Phase 2: Kronos inference wrapper

- Clone or install Kronos dependency strategy.
- Load Kronos-small and tokenizer.
- Run one-symbol prediction.
- Save forecast output.

### Phase 3: Signal and risk engine

- Convert forecasts to signals.
- Add risk_guard.
- Add tests for signal and risk decisions.

### Phase 4: Paper trading engine

- Simulate fills, fees, slippage, and PnL.
- Persist portfolio state and trade journal.
- Add paper trading tests.

### Phase 5: Reporting and monitoring

- Generate markdown and CSV reports.
- Add run status summary.
- Add failure reports.

### Phase 6: Backtesting and evaluation

- Replay historical data.
- Measure cumulative return, drawdown, win rate, and turnover.
- Compare Kronos-mini, Kronos-small, and optionally Kronos-base.

### Phase 7: Future live trading review gate

- Do not implement live trading here.
- Write a separate design document before adding exchange private endpoints.
- Require explicit user approval before any live trading implementation.

## 13. Open Decisions Deferred To Implementation Plan

These are intentionally deferred because they do not change the high-level design:

- exact Python package manager
- whether Kronos is vendored, cloned as a submodule, or installed from source
- exact report file naming
- exact Binance data client implementation
- exact threshold values for entry and exit signals
- whether Telegram notification is added after local reports work

## 14. Recommended Next Step

After this design is reviewed, the next step is to write an implementation plan that breaks the work into small, testable tasks.

The implementation plan should not enable live trading. It should focus on local paper trading and verifiable reports first.
