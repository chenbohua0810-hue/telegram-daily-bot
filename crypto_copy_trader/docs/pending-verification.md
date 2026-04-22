# Pending Verification

以下項目在本工作階段已重新盤點。可離線驗證者已補齊，以下只保留仍需要真實環境、外部服務或長時間執行的項目。

## Completed In This Worktree

- `pytest`
  - 本地實測 `126 passed`

- `pytest --cov`
  - 已補裝 `pytest-cov`
  - 本地實測總覆蓋率 `93%`，高於 `80%`

- 離線整合測試已覆蓋下列驗收點
  - 通過全部 filter 的事件會寫入 `status='paper'` trade
  - `decision_snapshots.trade_id` 會正確連回對應 trade
  - 被 quant filter 擋下的事件會寫入 `final_action='skip'`
  - `skip_reason='below_min_trade_usd'`
  - technical / sentiment / ai / risk / cost 欄位皆為 `NULL`

- 離線 wallet scorer 測試已確認
  - `evaluate_all()` 會在 `addresses.db` 寫入 history 紀錄

## Runtime Acceptance

- `python -m crypto_copy_trader.main` 在 `PAPER_TRADING=true` 下連續跑 1 小時無 crash
- Telegram 收到啟動通知
- `data/events.jsonl` 至少寫入 1 筆事件

## Wallet Scorer Runtime Check

- 切換 `PAPER_TRADING=false` 前，先手動跑一次 wallet scorer
  - `addresses.db` 應有 history 記錄

## 24h Paper Trading Health Check

- 連續跑 24 小時 paper trading 後，執行以下 SQL 健檢：

```sql
SELECT final_action, COUNT(*) FROM decision_snapshots GROUP BY final_action;
```

```sql
SELECT skip_reason, COUNT(*) FROM decision_snapshots WHERE final_action='skip' GROUP BY skip_reason;
```

```sql
SELECT AVG(realized_slippage_pct), AVG(estimated_slippage_pct) FROM trades WHERE status='paper';
```
