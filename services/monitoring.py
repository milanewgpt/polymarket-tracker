"""
Main monitoring loop — orchestrates fetch, decision, state update, notification.
Runs on each scheduler tick.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from clients.xtracker import XtrackerClient
from config.settings import Settings
from db.models import Event, EventState
from db.repository import Repository
from db.session import DatabaseManager
from domain.decision_engine import evaluate_transition
from domain.entities import RangeEntity
from services.notification import NotificationService

logger = logging.getLogger(__name__)


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite strips tzinfo — re-attach UTC when needed."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class MonitoringService:
    def __init__(
        self,
        db: DatabaseManager,
        xtracker: XtrackerClient,
        notification: NotificationService,
        settings: Settings,
    ) -> None:
        self.db = db
        self.xtracker = xtracker
        self.notification = notification
        self.settings = settings

    async def check_and_update(self) -> None:
        async with self.db.get_session() as session:
            repo = Repository(session)
            event = await repo.get_active_event()
            if event is None:
                return

            now = datetime.now(timezone.utc)

            # Mark completed if the event end time has passed
            ended_at = _ensure_aware(event.ended_at)
            if ended_at and ended_at <= now:
                await repo.mark_completed(event.id)
                await session.commit()
                logger.info("Event %d marked completed (end time passed)", event.id)
                return

            state = event.state
            if state is None:
                logger.error("Event %d has no state record — skipping", event.id)
                return

            # ── Fetch tweet count ───────────────────────────────────
            try:
                if event.xtracker_tracking_id:
                    tweet_count = await self.xtracker.get_tweet_count(
                        event.xtracker_tracking_id
                    )
                elif event.ended_at:
                    from datetime import timedelta
                    ended = _ensure_aware(event.ended_at)
                    start = ended - timedelta(days=7)
                    tweet_count = await self.xtracker.get_tweet_count_by_dates(
                        start, ended
                    )
                else:
                    logger.error("Event %d has no tracking ID or end date", event.id)
                    return
            except Exception as exc:
                await self._handle_fetch_error(repo, event, state, str(exc))
                await session.commit()
                return

            # ── Handle recovery from previous error ─────────────────
            last_err = _ensure_aware(state.last_error_at)
            last_rec = _ensure_aware(state.last_recovery_at)
            was_in_error = last_err is not None and (
                last_rec is None or last_rec < last_err
            )
            if was_in_error:
                state.last_recovery_at = now
                if not event.muted:
                    text = await self.notification.send_recovery(
                        event.chat_id, event.event_title
                    )
                else:
                    text = "[muted] Recovery"
                await repo.create_notification(
                    event.id, tweet_count, None, None, "recovery", text
                )

            # ── Build domain objects ────────────────────────────────
            ranges = self._to_entities(event.ranges)
            prev_factual = self._find_entity(ranges, state.factual_range_id)
            prev_notified = self._find_entity(ranges, state.notified_range_id)

            result = evaluate_transition(
                tweet_count,
                ranges,
                prev_factual,
                prev_notified,
                event.buffer_enabled,
                event.buffer_percent,
            )

            # ── Persist new state ───────────────────────────────────
            state.current_tweet_count = tweet_count
            state.last_success_check_at = now
            if result.current_factual_range:
                state.factual_range_id = result.current_factual_range.id
            if result.new_notified_range:
                state.notified_range_id = result.new_notified_range.id

            # ── Notify on transition ────────────────────────────────
            if result.should_notify:
                old_range_id = prev_notified.id if prev_notified else None
                new_range_id = (
                    result.new_notified_range.id if result.new_notified_range else None
                )

                if not event.muted:
                    text = await self.notification.send_range_notification(
                        chat_id=event.chat_id,
                        event_title=event.event_title,
                        event_url=event.event_url,
                        tweet_count=tweet_count,
                        result=result,
                        ranges=ranges,
                        buffer_enabled=event.buffer_enabled,
                        buffer_percent=event.buffer_percent,
                    )
                else:
                    text = f"[muted] {result.direction.value}: {result.reason}"

                state.last_notification_at = now
                await repo.create_notification(
                    event.id,
                    tweet_count,
                    old_range_id,
                    new_range_id,
                    result.direction.value,
                    text,
                )
                logger.info(
                    "Transition: %s -> %s (%s) count=%d",
                    prev_notified.label if prev_notified else "None",
                    result.new_notified_range.label
                    if result.new_notified_range
                    else "None",
                    result.direction.value,
                    tweet_count,
                )

            await session.commit()

    # ── Error handling ──────────────────────────────────────────────

    async def _handle_fetch_error(
        self,
        repo: Repository,
        event: Event,
        state: EventState,
        error_msg: str,
    ) -> None:
        now = datetime.now(timezone.utc)

        # Rate-limit error notifications
        should_send = True
        last_err_time = _ensure_aware(
            await repo.get_last_error_notification_time(event.id)
        )
        if last_err_time:
            cutoff = now - timedelta(hours=self.settings.error_rate_limit_hours)
            if last_err_time >= cutoff:
                should_send = False

        state.last_error_at = now
        state.last_error_message = error_msg

        if should_send and not event.muted:
            text = await self.notification.send_error(
                event.chat_id, event.event_title, error_msg
            )
            await repo.create_notification(event.id, None, None, None, "error", text)

        logger.warning("Fetch error for event %d: %s", event.id, error_msg)

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _to_entities(db_ranges: list) -> list[RangeEntity]:
        return [
            RangeEntity(
                id=r.id,
                label=r.label,
                min_value=r.min_value,
                max_value=r.max_value,
                sort_order=r.sort_order,
            )
            for r in sorted(db_ranges, key=lambda x: x.sort_order)
        ]

    @staticmethod
    def _find_entity(
        ranges: list[RangeEntity], range_id: Optional[int]
    ) -> Optional[RangeEntity]:
        if range_id is None:
            return None
        for r in ranges:
            if r.id == range_id:
                return r
        return None
