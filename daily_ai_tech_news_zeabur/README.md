# Daily AI Tech News on Zeabur

雲端版每日 AI / 科技新聞 Telegram 摘要服務。

## 功能

- 每天 08:00 Asia/Taipei 執行。
- 只收 AI 相關新聞；不足 5 則時寧可少發，也不補一般科技新聞。
- 過濾過去 24 小時內的新聞；若 RSS 來源沒有提供時間戳，會保留但依 AI 相關性排序。
- 發送 5 則「繁體中文標題 + 文章實際重點」到 Telegram。
- 可選用 Gemini API 將英文標題翻成繁體中文，並依標題/摘要生成文章本身的重點。
- 不需要本機常駐。

## 隱私與外部 API

執行時會呼叫：

- 公開 RSS / 公開新聞來源，例如 Google News RSS、TechCrunch、The Verge、Hacker News RSS。
- Google Gemini API（選用）：若設定 `GEMINI_API_KEY`，會呼叫 Gemini 產生繁體中文標題與文章實際重點。
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
GEMINI_API_KEY=Google AI Studio Gemini API key，用於翻譯標題與生成文章實際重點
TRANSLATE_TITLES=true
TRANSLATION_MODEL=gemini-2.5-pro
```

`TELEGRAM_CHAT_ID` 請填你的 Telegram chat_id。
Bot Token 與 Gemini API key 請不要貼到聊天裡，請你自己從原本 Zeabur bot service / Google AI Studio 複製到這個 digest service 的 Variables。

## Secrets handoff 檔案

我已建立本機 secrets 範本：

```text
/Users/chenbohua/Downloads/ai_claude/daily_ai_tech_news_zeabur/secrets.env
```

請你自己用編輯器填入 `TELEGRAM_BOT_TOKEN` 與 `GEMINI_API_KEY`。不要把 token / API key 貼到聊天裡。
這個檔案已被 `.gitignore` 與 `.dockerignore` 排除，不會提交或打包進 Docker image。

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
