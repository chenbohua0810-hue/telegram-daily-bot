# Verification Checklist

## Automated

- [x] `pytest` 全綠
- [ ] `pytest --cov=crypto_copy_trader` 覆蓋率 ≥ 80%

## Runtime Acceptance

- [ ] `python -m crypto_copy_trader.main` 在 paper trading 模式下可啟動、連續跑 1 小時無 crash
- [ ] Telegram 收到啟動通知
- [ ] `data/events.jsonl` 有至少 1 筆事件寫入
- [ ] 手動植入一個會通過全部 filter 的假事件後，`trades.db` 出現 `status='paper'` 的 buy 紀錄，且 `decision_snapshots.trade_id` 連結正確
- [ ] 手動植入一個會被 quant filter 擋下的假事件後，`decision_snapshots` 出現 `final_action='skip'`、`skip_reason='below_min_trade_usd'`，technical / sentiment / ai / risk / cost 皆為 `NULL`
- [ ] 切換 `PAPER_TRADING=false` 前，先手動跑一次 wallet scorer，確認 `addresses.db` 有 history 記錄

## 24h Paper Trading SQL Health Checks

- [ ] `SELECT final_action, COUNT(*) FROM decision_snapshots GROUP BY final_action;`
- [ ] `SELECT skip_reason, COUNT(*) FROM decision_snapshots WHERE final_action='skip' GROUP BY skip_reason;`
- [ ] `SELECT AVG(realized_slippage_pct), AVG(estimated_slippage_pct) FROM trades WHERE status='paper';`
