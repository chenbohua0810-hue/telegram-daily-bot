# Daily AI Tech News on Zeabur

雲端版每日 AI / 科技新聞 Telegram 摘要服務。

## 功能

- 每天 08:00 Asia/Taipei 執行。
- 從公開 RSS / 公開新聞來源抓取科技新聞。
- AI 優先排序，不足時補半導體、雲端、資安、開發者工具、新創等科技新聞。
- 發送 5 則繁體中文摘要到 Telegram。
- 不需要本機常駐。

## 隱私與外部 API

執行時會呼叫：

- 公開 RSS / 公開新聞來源，例如 Google News RSS、TechCrunch、The Verge、Hacker News RSS。
- Telegram Bot API：`https://api.telegram.org/bot.../sendMessage`。

不會使用：

- 你的私人帳號。
- cookies。
- 付費牆內容。
- 任何我能看到的 Telegram Bot Token。請只在 Zeabur Variables 裡自行填入。

## 必填 Zeabur Variables

可以沿用之前已部署在雲端的 Telegram bot token。這個服務只呼叫 Telegram `sendMessage` 發送每日摘要，不會啟動 polling / webhook 收訊，所以通常不會跟原本的 Hermes Telegram bot 搶 `getUpdates`。

在 Zeabur 專案的 Variables 裡填：

```env
TELEGRAM_BOT_TOKEN=沿用之前雲端 bot 的 Telegram Bot Token
TELEGRAM_CHAT_ID=你的 Telegram chat_id
TZ=Asia/Taipei
SEND_HOUR=8
SEND_MINUTE=0
ITEM_LIMIT=5
```

如果要發到剛剛測試過的 Telegram home channel，可使用先前測試回傳的 chat_id：`7407011243`。
Bot Token 請不要貼到聊天裡，請你自己從原本 Zeabur bot service 的 Variables 複製到這個 digest service 的 Variables。

## Zeabur 部署步驟

1. 把這個資料夾推到一個 GitHub repo。
2. 在 Zeabur 新增 Project。
3. 選擇 Deploy from GitHub，選這個 repo。
4. Zeabur 偵測到 Dockerfile 後直接 build。
5. 在 Variables 填入上面的環境變數。
6. 部署後看 logs，應會看到類似：

```text
INFO next run at 2026-05-05T08:00:00+08:00 (...s)
```

## 測試一次發送

如果你想在 Zeabur 上先手動測試一次：

1. 暫時設定：

```env
RUN_ONCE=true
```

2. Redeploy。
3. 確認 Telegram 收到訊息。
4. 測完後把 `RUN_ONCE` 清空或改成 false，再 Redeploy，讓服務回到每日排程模式。

## 本機測試

不需要 Telegram Token 的單元測試：

```bash
uv run --with pytest pytest
```

如果要本機試跑一次，請自行建立 `.env` 或手動 export：

```bash
export TELEGRAM_BOT_TOKEN='你的 token'
export TELEGRAM_CHAT_ID='你的 chat id'
export RUN_ONCE=true
PYTHONPATH=src python -m daily_ai_tech_news.main
```

注意：如果你的目標是完全不用本機發送，就不要在本機設定 token 試跑；直接在 Zeabur Variables 設定即可。

## 自訂 RSS 來源

可用 `NEWS_RSS_URLS` 覆蓋預設來源，支援逗號或換行分隔。

預設來源包含：

- Google News RSS：AI / artificial intelligence technology 搜尋
- TechCrunch RSS
- The Verge RSS
- Hacker News RSS
