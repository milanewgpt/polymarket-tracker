import logging
from datetime import datetime, timezone

from aiogram import Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.formatters import (
    format_count,
    format_event_summary,
    format_history,
    format_list,
    format_status,
)
from clients.polymarket import PolymarketClient, PolymarketParseError
from clients.xtracker import XtrackerClient
from config.settings import Settings
from db.repository import Repository
from db.session import DatabaseManager
from domain.entities import RangeEntity
from domain.range_utils import find_range_for_count, get_next_range

logger = logging.getLogger(__name__)
router = Router()


# ── /start ──────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    text = (
        "<b>Polymarket Tweet Tracker</b>\n\n"
        "Commands:\n"
        "/add &lt;url&gt; \u2014 add weekly event\n"
        "/delete \u2014 remove active event\n"
        "/list \u2014 show all events\n"
        "/status \u2014 current status\n"
        "/count \u2014 quick tweet count\n"
        "/mute \u2014 silence notifications\n"
        "/unmute \u2014 enable notifications\n"
        "/buffer_on \u2014 enable buffer\n"
        "/buffer_off \u2014 disable buffer\n"
        "/buffer_value &lt;n&gt; \u2014 set buffer %\n"
        "/history \u2014 recent transitions"
    )
    await message.answer(text, parse_mode="HTML")


# ── /add ────────────────────────────────────────────────────────────


@router.message(Command("add"))
async def cmd_add(
    message: Message,
    db_manager: DatabaseManager,
    settings: Settings,
    polymarket_client: PolymarketClient,
    xtracker_client: XtrackerClient,
) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /add &lt;polymarket_event_url&gt;", parse_mode="HTML")
        return

    url = parts[1].strip()
    if not PolymarketClient.validate_url(url):
        await message.answer("\u274c Invalid Polymarket event URL.")
        return

    # Parse event from Polymarket
    try:
        slug = PolymarketClient.extract_slug(url)
        event_data = await polymarket_client.fetch_event_data(slug)
        title, ranges_parsed, end_date, start_time = polymarket_client.parse_event(event_data)
    except PolymarketParseError as exc:
        await message.answer(f"\u274c Parse error: {exc}")
        return
    except Exception as exc:
        logger.exception("Polymarket fetch failed")
        await message.answer(f"\u274c Failed to fetch event: {exc}")
        return

    # Find matching Xtracker tracking and fetch initial tweet count
    tracking_id: str | None = None
    try:
        # For time-windowed markets (start_time set), skip weekly tracking lookup
        # and count posts directly for the exact window.
        tracking_info = await xtracker_client.find_tracking_for_event(
            url, event_end_date=None if start_time else end_date
        )
        if tracking_info:
            tracking_id = tracking_info.tracking_id
            tweet_count = await xtracker_client.get_tweet_count(tracking_id)
        elif start_time and end_date:
            tweet_count = await xtracker_client.get_tweet_count_by_dates(
                start_time.isoformat(), end_date.isoformat()
            )
        elif end_date:
            from datetime import timedelta
            tweet_count = await xtracker_client.get_tweet_count_by_dates(
                (end_date - timedelta(days=7)).isoformat(), end_date.isoformat()
            )
        else:
            await message.answer(
                "\u274c No matching tracking found on Xtracker for this event."
            )
            return
    except Exception as exc:
        logger.exception("Xtracker fetch failed during /add")
        await message.answer(f"\u274c Failed to fetch tweet count: {exc}")
        return

    # Persist
    async with db_manager.get_session() as session:
        repo = Repository(session)

        await repo.deactivate_current_active()

        event = await repo.create_event(
            chat_id=message.chat.id,
            event_url=url,
            event_title=title,
            source_url=settings.xtracker_source_url,
            ended_at=end_date,
            started_at=start_time,
            buffer_enabled=settings.default_buffer_enabled,
            buffer_percent=settings.default_buffer_percent,
            check_interval_minutes=settings.default_check_interval_minutes,
            xtracker_tracking_id=tracking_id,
        )

        db_ranges = await repo.create_ranges(event.id, ranges_parsed)

        range_entities = [
            RangeEntity(
                id=r.id,
                label=r.label,
                min_value=r.min_value,
                max_value=r.max_value,
                sort_order=r.sort_order,
            )
            for r in db_ranges
        ]
        factual = find_range_for_count(tweet_count, range_entities)
        next_range_entity = get_next_range(factual, range_entities) if factual else None

        state = await repo.create_state(event.id)
        state.current_tweet_count = tweet_count
        state.factual_range_id = factual.id if factual else None
        state.notified_range_id = factual.id if factual else None
        state.last_success_check_at = datetime.now(timezone.utc)

        await session.commit()

        factual_db = next((r for r in db_ranges if factual and r.id == factual.id), None)
        next_db = next(
            (r for r in db_ranges if next_range_entity and r.id == next_range_entity.id),
            None,
        )

        summary = format_event_summary(event, db_ranges, tweet_count, factual_db, next_db)
        await message.answer(summary, parse_mode="HTML", disable_web_page_preview=True)


# ── /delete ─────────────────────────────────────────────────────────


@router.message(Command("delete"))
async def cmd_delete(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event to delete.")
            return
        title = event.event_title
        await repo.delete_event(event.id)
        await session.commit()
    await message.answer(f"\U0001f5d1\ufe0f Deleted: {title}")


# ── /list ───────────────────────────────────────────────────────────


@router.message(Command("list"))
async def cmd_list(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        events = await repo.get_all_events()
        text = format_list(events)
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ── /status ─────────────────────────────────────────────────────────


@router.message(Command("status"))
async def cmd_status(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        ranges = sorted(event.ranges, key=lambda r: r.sort_order)
        text = format_status(event, event.state, ranges)
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ── /count ──────────────────────────────────────────────────────────


@router.message(Command("count"))
async def cmd_count(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        ranges = sorted(event.ranges, key=lambda r: r.sort_order)
        text = format_count(event, event.state, ranges)
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ── /mute & /unmute ────────────────────────────────────────────────


@router.message(Command("mute"))
async def cmd_mute(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        event.muted = True
        await session.commit()
    await message.answer("\U0001f507 Notifications muted. Monitoring continues.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        event.muted = False
        await session.commit()
    await message.answer("\U0001f514 Notifications enabled.")


# ── /buffer_on, /buffer_off, /buffer_value ─────────────────────────


@router.message(Command("buffer_on"))
async def cmd_buffer_on(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        event.buffer_enabled = True
        await session.commit()
    await message.answer(f"\u2705 Buffer ON ({event.buffer_percent}%)")


@router.message(Command("buffer_off"))
async def cmd_buffer_off(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        event.buffer_enabled = False
        await session.commit()
    await message.answer("\u2705 Buffer OFF")


@router.message(Command("buffer_value"))
async def cmd_buffer_value(message: Message, db_manager: DatabaseManager) -> None:
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Usage: /buffer_value &lt;number&gt;", parse_mode="HTML")
        return
    try:
        value = float(args[1])
        if not 0 <= value <= 100:
            raise ValueError
    except ValueError:
        await message.answer("\u274c Value must be a number between 0 and 100.")
        return

    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        event.buffer_percent = value
        await session.commit()
    await message.answer(f"\u2705 Buffer set to {value}%")


# ── /history ────────────────────────────────────────────────────────


@router.message(Command("history"))
async def cmd_history(message: Message, db_manager: DatabaseManager) -> None:
    async with db_manager.get_session() as session:
        repo = Repository(session)
        event = await repo.get_active_event()
        if not event:
            await message.answer("No active event.")
            return
        logs = await repo.get_recent_notifications(event.id, limit=10)
        text = format_history(logs)
    await message.answer(text, parse_mode="HTML")


# ── plain URL → /add ────────────────────────────────────────────────


@router.message()
async def handle_plain_url(
    message: Message,
    db_manager: DatabaseManager,
    settings: Settings,
    polymarket_client: PolymarketClient,
    xtracker_client: XtrackerClient,
) -> None:
    text = (message.text or "").strip()
    if not PolymarketClient.validate_url(text):
        return
    message.text = f"/add {text}"
    await cmd_add(message, db_manager, settings, polymarket_client, xtracker_client)


# ── Registration ────────────────────────────────────────────────────


def register_handlers(
    dp: Dispatcher,
    db_manager: DatabaseManager,
    settings: Settings,
    polymarket_client: PolymarketClient,
    xtracker_client: XtrackerClient,
) -> None:
    dp["db_manager"] = db_manager
    dp["settings"] = settings
    dp["polymarket_client"] = polymarket_client
    dp["xtracker_client"] = xtracker_client
    dp.include_router(router)
