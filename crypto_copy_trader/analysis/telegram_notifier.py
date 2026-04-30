from __future__ import annotations

import logging


logger = logging.getLogger(__name__)
MARKDOWN_V2_SPECIALS = "_*[]()~`>#+-=|{}.!"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, *, bot=None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = bot

    async def notify_trade_fill(self, decision, result) -> None:
        text = "\n".join(
            [
                "*🟢 Copy Trade Filled*",
                f"Symbol: `{self._escape(decision.symbol)}`",
                f"Action: `{self._escape(decision.action)}`",
                f"Size: `${decision.quantity_usdt:.2f}`",
                f"Price: `${result.avg_price}`",
                f"Wallet: `{self._escape(decision.source_wallet[:8])}...`",
                f"Confidence: `{decision.confidence}`",
                f"Reason: {self._escape(decision.reasoning)}",
            ]
        )
        await self._send(text)

    async def notify_trade_skip(self, event, reason: str) -> None:
        text = f"*Skip* `{self._escape(event.token_symbol)}` {self._escape(reason)}"
        await self._send(text)

    async def notify_risk_alert(self, message: str) -> None:
        await self._send(f"*Risk Alert* {self._escape(message)}")

    async def notify_daily_summary(
        self,
        date: str,
        total_trades: int,
        win_rate: float,
        pnl_pct: float,
    ) -> None:
        text = (
            f"*Daily Summary* `{self._escape(date)}`\n"
            f"Trades: `{total_trades}`\n"
            f"Win Rate: `{win_rate:.2%}`\n"
            f"PnL: `{pnl_pct:.2%}`"
        )
        await self._send(text)

    async def _send(self, text: str) -> None:
        if self.bot is None:
            return
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="MarkdownV2",
            )
        except Exception:
            logger.error("Telegram notification failed", exc_info=True)

    async def initialize(self) -> None:
        if self.bot is None:
            return
        try:
            await self.bot.initialize()
        except Exception:
            logger.warning("Telegram bot initialize failed", exc_info=True)

    async def aclose(self) -> None:
        if self.bot is None:
            return
        shutdown = getattr(self.bot, "shutdown", None)
        if shutdown is None:
            return
        try:
            await shutdown()
        except Exception:
            logger.warning("Telegram bot shutdown failed", exc_info=True)

    def _escape(self, value: str) -> str:
        escaped = value
        for char in MARKDOWN_V2_SPECIALS:
            escaped = escaped.replace(char, f"\\{char}")
        return escaped
