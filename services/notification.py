import logging
from typing import Optional

from aiogram import Bot
from aiogram.enums import ParseMode

from domain.entities import DecisionResult, RangeEntity, TransitionDirection
from domain.range_utils import get_next_range

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_range_notification(
        self,
        *,
        chat_id: int,
        event_title: str,
        event_url: str,
        tweet_count: int,
        result: DecisionResult,
        ranges: list[RangeEntity],
        buffer_enabled: bool,
        buffer_percent: float,
    ) -> str:
        assert result.new_notified_range is not None
        next_range = get_next_range(result.new_notified_range, ranges)
        next_text = next_range.label if next_range else "\u2014"

        if result.direction == TransitionDirection.UP:
            buffer_line = ""
            if buffer_enabled:
                buffer_line = f"\n\U0001f4ca Mode: buffer ON (+{buffer_percent}%)"
            text = (
                f"\U0001f4c8 <b>{event_title}</b>\n\n"
                f"Current tweets: <b>{tweet_count}</b>\n"
                f"New active range: <b>{result.new_notified_range.label}</b>\n"
                f"Next range: {next_text}"
                f"{buffer_line}\n\n"
                f'\U0001f517 <a href="{event_url}">Event</a>'
            )
        elif result.direction == TransitionDirection.DOWN:
            text = (
                f"\U0001f4c9 <b>{event_title}</b>\n\n"
                f"Current tweets: <b>{tweet_count}</b>\n"
                f"New active range: <b>{result.new_notified_range.label}</b>\n"
                f"Next range: {next_text}\n"
                f"Reason: source correction / moved back down\n\n"
                f'\U0001f517 <a href="{event_url}">Event</a>'
            )
        else:
            return ""

        await self._send(chat_id, text)
        return text

    async def send_error(self, chat_id: int, event_title: str, error: str) -> str:
        text = (
            f"\u26a0\ufe0f <b>Monitoring Error</b>\n\n"
            f"Event: {event_title}\n"
            f"Error: {error}"
        )
        await self._send(chat_id, text)
        return text

    async def send_recovery(self, chat_id: int, event_title: str) -> str:
        text = (
            f"\u2705 <b>Monitoring Recovered</b>\n\n"
            f"Event: {event_title}\n"
            f"Source is responding normally again."
        )
        await self._send(chat_id, text)
        return text

    async def send_text(self, chat_id: int, text: str) -> None:
        await self._send(chat_id, text)

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(
                chat_id,
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Failed to send Telegram message to %s", chat_id)
