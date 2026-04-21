# Crypto Copy Trader — Agents 整合設計

**日期**: 2026-04-21  
**來源 repo**: virattt/ai-hedge-fund、msitarzewski/agency-agents  
**架構決策**: 簡單函數 pipeline（非 LangGraph），從兩個 repo 借邏輯，剝除框架依賴

---

## 1. 模組結構

```
crypto_copy_trader/
├── monitors/              # Layer 1 - 鏈上偵測
│   ├── eth_monitor.py
│   ├── sol_monitor.py
│   └── bsc_monitor.py
│
├── signals/               # Layer 2 - 信號處理
│   ├── quant_filter.py        # 金額/幣種過濾
│   ├── technicals.py          # 移植自 technical_analyst_agent
│   ├── sentiment.py           # 移植自 sentiment_analyst_agent
│   ├── ai_scorer.py           # Claude Haiku 綜合信號
│   └── slippage_fee.py        # 成本估算
│
├── execution/             # Layer 3 - 執行
│   ├── position_sizer.py      # 移植自 risk_management_agent
│   ├── binance_executor.py    # ccxt 下單
│   └── risk_guard.py          # 移植自 risk_management_agent
│
├── analysis/              # Layer 4 - 分析與通知
│   ├── trade_logger.py
│   ├── performance_tracker.py
│   └── telegram_notifier.py
│
├── wallet_scorer/         # 週期性地址評估
│   └── scorer.py              # 框架參考 agency-agents investment-researcher
│
└── models/                # 共享資料模型
    └── decision.py            # 移植自 PortfolioDecision
```

---

## 2. 資料流

```
鏈上事件
  → quant_filter.py      （金額門檻、幣種是否上 Binance）
  → technicals.py        （Binance OHLCV → 動量/趨勢/波動率信號）
  → sentiment.py         （加密新聞情緒 → bullish/bearish/neutral）
  → ai_scorer.py         （Haiku 綜合 → confidence 0-100）
  → slippage_fee.py      （成本 > 預期報酬 30% → 丟棄）
  → position_sizer.py    （波動率調整倉位計算）
  → risk_guard.py        （相關性檢查、熔斷、曝險上限）
  → binance_executor.py  （ccxt 下單，paper trading 模式）
```

---

## 3. 移植模組詳細規格

### 3.1 `signals/technicals.py`

**來源**: `virattt/ai-hedge-fund` → `src/agents/technicals.py`  
**移植方式**: 剝除 `AgentState`，改為純函數輸入 OHLCV DataFrame

計算四個信號：

| 信號 | 計算方式 |
|---|---|
| 趨勢 | EMA 8/21 黃金/死亡交叉 |
| 動量 | RSI 14、MACD histogram |
| 波動率 | ATR / 近期價格標準差 |
| 統計套利 | 偏離布林帶 z-score |

**輸出**：
```python
@dataclass(frozen=True)
class TechnicalSignal:
    trend: Literal["bullish", "bearish", "neutral"]
    momentum: Literal["bullish", "bearish", "neutral"]
    volatility: Literal["low", "medium", "high"]
    confidence: float  # 0.0–1.0
```

資料來源：Binance OHLCV（ccxt，與 BinanceExecutor 共用連線）

---

### 3.2 `signals/sentiment.py`

**來源**: `virattt/ai-hedge-fund` → `src/agents/sentiment.py`  
**移植方式**: 替換股票新聞/內部人交易 → 加密貨幣新聞來源

- **新聞來源**: CryptoPanic API（免費 tier，同時提供新聞情緒與社群提及量）
- **信號加權**: 新聞情緒分類（positive/negative/neutral）70%、同幣種 24h 提及量變化率 30%

**輸出**：
```python
@dataclass(frozen=True)
class SentimentSignal:
    signal: Literal["bullish", "bearish", "neutral"]
    score: float       # 0.0–1.0
    source_count: int  # 樣本數
```

無資料時 `score = 0.5`（中性），流程繼續而非中斷。

---

### 3.3 `execution/risk_guard.py` + `execution/position_sizer.py`

**來源**: `virattt/ai-hedge-fund` → `src/agents/risk_manager.py`  
**移植方式**: 剝除 AgentState，改為輸入持倉 dict + 新標的資料

**PositionSizer — 波動率調整倉位**：
```
target_vol      = 0.02                         # 目標日波動率 2%（固定常數）
base_position   = portfolio_value × 0.10       # 單幣上限 10%
vol_adjustment  = target_vol / asset_vol       # 高波動 → 縮倉
final_position  = min(base_position × vol_adjustment, available_cash)
```

**RiskGuard — 三道檢查**：
1. 相關性矩陣：新標的與現有持倉相關性 > 0.8 → 倉位縮 50%
2. 每日虧損熔斷：當日 PnL < -5% → 停止所有新信號
3. 最多 10 個同時持倉

---

### 3.4 `models/decision.py`

**來源**: `virattt/ai-hedge-fund` → `src/agents/portfolio_manager.py`（`PortfolioDecision`）

```python
@dataclass(frozen=True)
class TradeDecision:
    action: Literal["buy", "sell", "hold", "skip"]
    symbol: str
    quantity_usdt: float
    confidence: int      # 0–100
    reasoning: str       # 一句話，來自 Haiku
    source_wallet: str
```

所有 pipeline 步驟均傳遞此結構，確保每筆決策可追溯。

---

### 3.5 `wallet_scorer/scorer.py`

**來源**: `msitarzewski/agency-agents` → `finance/finance-investment-researcher.md`  
**移植方式**: 借用 thesis/thesis-breaker 框架作為 Claude 系統提示結構

investment-researcher 概念對應：

| 股票研究概念 | 地址評估對應 |
|---|---|
| Thesis breakers | 連續 3 筆虧損 → 列入觀察名單 |
| Conviction level | 勝率分位數 → High / Med / Low |
| Exit triggers | 最大回撤 > 40% → 自動淘汰 |
| Investment horizon | 持倉時長範圍 1h–30 天 |

每週執行一次，輸入：地址歷史績效 → 輸出：保留 / 觀察 / 淘汰

---

## 4. `ai_scorer.py` 整合方式

Claude Haiku 收到結構化 context，只負責綜合判斷：

**Prompt 輸入**：
```
鏈上事件：{wallet, symbol, amount_usd, tx_type}
技術信號：{trend, momentum, volatility, confidence}
情緒信號：{signal, score, source_count}
錢包資料：{win_rate, trade_count, max_drawdown, trust_level}
```

**要求輸出**：
```json
{
  "confidence_score": 0-100,
  "reasoning": "一句話",
  "recommendation": "execute | skip"
}
```

閾值：`confidence_score < 60` → 信號丟棄，不進入執行層。

---

## 5. 錯誤處理

| 層級 | 失敗情境 | 處理方式 |
|---|---|---|
| 鏈上偵測 | API 逾時 | 跳過本輪，下次輪詢補 |
| technicals | K 線資料不足 | 波動率預設 0.05，trend = neutral |
| sentiment | CryptoPanic 無資料 | score = 0.5，繼續流程 |
| ai_scorer | Haiku API 失敗 | 整個信號丟棄，記 log，不執行交易 |
| binance_executor | 下單失敗 | 最多重試 2 次，仍失敗 → Telegram 告警 |
| risk_guard | 熔斷觸發 | 停止當日新信號，保持現有持倉 |

---

## 6. 測試策略

**Unit tests**：
- `technicals.py`：餵假 OHLCV → 驗證信號方向
- `risk_guard.py`：高相關性持倉 → 驗證縮倉邏輯
- `position_sizer.py`：極高/低波動率邊界值

**Integration tests**：
- 完整 pipeline 跑歷史鏈上事件 → 驗證 `TradeDecision` 輸出格式
- Paper trading 模式 24 小時跑通不崩潰

**v1 範圍外**：
- E2E 連真實 Binance
- Backtesting framework

---

## 7. v1 不做（沿用大綱）

DEX 直接上鏈、WebSocket 即時監聽、做空/衍生品、Web Dashboard、Druckenmiller 動量信號層（預留 v2）
