# Pending Verification

以下項目在本 worktree 已重新盤點。離線可驗證項目已完成，現在剩下的都是需要真實環境、外部服務或長時間執行的驗收。

## Completed In This Worktree

- `pytest tests/ --cov=. --cov-report=term-missing -q`
  - 本地實測 `200 passed`
  - coverage `92.56%`

- 已完成並覆蓋測試的功能
  - Priority router（P0 / P1 / P2 / P3）
  - Anthropic / OpenAI-compatible / fallback backends
  - Batch scorer（window flush / max batch flush / token overflow split）
  - `main.py` runtime routing integration
  - WebSocket monitor reconnect / heartbeat timeout / gap backfill
  - runtime health metrics

## Remaining Runtime Acceptance

- `python -m crypto_copy_trader.main` 在 `PAPER_TRADING=true` 下連續跑 1 小時無 crash
- Telegram 收到啟動通知
- `data/events.jsonl` 至少寫入 1 筆真實事件
- WebSocket 模式若啟用，確認至少一條鏈的 stream 可穩定接收事件
- 切換 `PAPER_TRADING=false` 前，手動跑一次 wallet scorer 並確認 `wallet_history` 有新增紀錄

## 24h Paper Trading Health Check

主程式連跑 24 小時後，執行：

```bash
./.venv/bin/python -m verification.runtime_health --hours 24
```

預期至少可看到下列欄位：
- `event_count`
- `wallet_history_count`
- `snapshot_action_counts`
- `skip_reason_counts`
- `paper_trade_count`
- `avg_estimated_slippage_pct`
- `avg_realized_slippage_pct`
- `backend_fallback_rate`
- `batch_flush_latency_ms`
- `ws_reconnect_count`
