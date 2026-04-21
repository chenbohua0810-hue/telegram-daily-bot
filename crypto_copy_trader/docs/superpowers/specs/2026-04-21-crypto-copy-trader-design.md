# Crypto Copy Trader — Design Spec

**Date:** 2026-04-21
**Status:** Approved

---

## Overview

An independent automated crypto copy-trading system that monitors on-chain addresses with high win-rates and large capital, then executes corresponding trades on Binance. On-chain data is used exclusively for signal detection; all execution happens on CEX (Binance) to avoid private key management and gas complexity.

---

## Architecture

### System Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                  crypto_copy_trader/                            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 1: Chain Monitor                                  │   │
│  │                                                          │   │
│  │  EthMonitor   SolanaMonitor   BSCMonitor                 │   │
│  │  (Etherscan)  (Solscan)       (BSCscan)                  │   │
│  │       └──────────┬──────────────┘                        │   │
│  │                  ↓ new transaction events                │   │
│  └──────────────────┼───────────────────────────────────────┘   │
│                     ↓                                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 2: Signal Pipeline                                │   │
│  │                                                          │   │
│  │  QuantFilter → AIScorer → SlippageFeeEstimator           │   │
│  │  (win-rate/   (Claude    (slippage + fee                 │   │
│  │   size)        Haiku)     pre-check)                     │   │
│  └──────────────────┬───────────────────────────────────────┘   │
│                     ↓ approved signals                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 3: Execution                                      │   │
│  │                                                          │   │
│  │  PositionSizer → BinanceExecutor → RiskGuard             │   │
│  │  (fixed % of    (market/limit     (stop-loss /           │   │
│  │   capital)       order)            exposure cap)         │   │
│  └──────────────────┬───────────────────────────────────────┘   │
│                     ↓                                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 4: Analytics & Notifier                           │   │
│  │                                                          │   │
│  │  TradeLogger → PerformanceTracker → TelegramNotifier     │   │
│  │  (JSON/SQLite)  (win-rate/ROI)      (Telegram push)      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AddressManager                                          │   │
│  │  Nansen/Arkham → QuantFilter → AIScorer → Watchlist      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
On-chain new tx → QuantFilter → AIScorer → SlippageFeeEstimator
               → PositionSizer → BinanceExecutor → TradeLogger + Notifier
```

---

## Agent Responsibilities

| Agent | Responsibility | Technology |
|---|---|---|
| `AddressManager` | Fetch labeled addresses from Nansen/Arkham, run quantitative filter, AI scoring, maintain watchlist | Nansen API + Claude Haiku |
| `EthMonitor` | Poll Etherscan for new txs from tracked addresses, push to event queue | Etherscan API |
| `SolanaMonitor` | Poll Solscan for Solana tracked addresses | Solscan API |
| `BSCMonitor` | Poll BSCscan for BSC/BNB chain tracked addresses | BSCscan API |
| `QuantFilter` | Filter events: min trade size, token listed on Binance, dedup same-address rapid trades | Pure Python |
| `AIScorer` | Send trade context (address history, market condition, trade size) to Claude; output confidence score 0–10 | Claude Haiku |
| `SlippageFeeEstimator` | Estimate slippage from Binance order book depth + taker fee; reject if cost > 30% of expected profit | Binance API |
| `PositionSizer` | Calculate order size as fixed % of total capital (e.g. 2%), respecting Binance min order limits | Pure Python |
| `BinanceExecutor` | Place market or limit orders on Binance; supports paper trading mode | ccxt |
| `RiskGuard` | Per-token exposure cap, daily loss circuit breaker, max concurrent positions | Pure Python |
| `PerformanceTracker` | Track per-address copy-trade win-rate, avg ROI, max drawdown; auto-delist underperformers weekly | SQLite |
| `TelegramNotifier` | Push trade fills, daily summaries, and anomaly alerts | Telegram Bot API |

**Notes:**
- `AIScorer` uses **Claude Haiku** (not Opus/Sonnet) to reduce token cost at high signal frequency
- `AddressManager` re-evaluates all tracked addresses weekly; automatically removes addresses whose win-rate drops below threshold
- On-chain monitoring uses polling (not WebSocket) to avoid persistent connection management complexity

---

## Slippage & Fee Model

```
Total estimated cost = slippage + trading fee

Slippage estimation:
  Small order  (< $10K USD):   fixed 0.1%
  Medium order ($10K–$100K):   query Binance order book depth, compute price impact
  Large order  (> $100K):      split into chunks, estimate each chunk

Binance taker fee:
  Default: 0.1% per side → 0.2% round-trip
  With BNB discount: 0.075% per side → 0.15% round-trip

Rejection threshold:
  If (slippage + fee) > expected_profit × 30% → reject signal
  Example: expected +2%, cost > 0.6% → reject
```

---

## Address Qualification Thresholds

| Metric | Initial Threshold |
|---|---|
| Historical win-rate | ≥ 55% |
| Average holding period | 1h – 30 days (excludes MEV bots) |
| Minimum capital size | ≥ $100K USD |
| Minimum trade count | ≥ 20 trades (sufficient sample) |
| Maximum drawdown | ≤ 40% |

These values are configurable in `config.py`.

---

## Data Storage

```
crypto_copy_trader/
├── data/
│   ├── addresses.db     ← SQLite: tracked addresses, scores, historical performance
│   ├── trades.db        ← SQLite: all copy-trade records, P&L
│   └── events.jsonl     ← raw on-chain event log (append-only)
├── agents/
│   ├── address_manager.py
│   ├── chain_monitors/
│   │   ├── __init__.py
│   │   ├── eth_monitor.py
│   │   ├── sol_monitor.py
│   │   └── bsc_monitor.py
│   ├── quant_filter.py
│   ├── ai_scorer.py
│   ├── slippage_fee_estimator.py
│   ├── position_sizer.py
│   ├── binance_executor.py
│   ├── risk_guard.py
│   └── performance_tracker.py
├── notifications/
│   └── notifier.py
├── config.py
├── main.py
├── requirements.txt
└── .env.example
```

---

## Risk Controls

- **Per-token exposure:** max 10% of total capital in any single token
- **Daily loss circuit breaker:** halt trading if daily P&L drops below -5%
- **Max concurrent positions:** configurable (default: 10)
- **Paper trading mode:** default on; switch to live via `PAPER_TRADING=false` in `.env`
- **Signal deduplication:** ignore repeated trades from same address within 10 minutes

---

## Out of Scope (v1)

- Direct on-chain DEX execution (no private key management)
- WebSocket-based real-time monitoring (polling is sufficient for v1)
- Cross-chain arbitrage
- Shorting / derivatives trading
- Web dashboard UI
