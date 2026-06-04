from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Event, EventState, NotificationLog, Range


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Events ──────────────────────────────────────────────────────

    async def get_active_event(self) -> Optional[Event]:
        result = await self.session.execute(
            select(Event)
            .where(Event.status == "active")
            .options(
                selectinload(Event.ranges),
                selectinload(Event.state).selectinload(EventState.factual_range),
                selectinload(Event.state).selectinload(EventState.notified_range),
            )
        )
        return result.scalar_one_or_none()

    async def get_all_events(self) -> Sequence[Event]:
        result = await self.session.execute(
            select(Event)
            .where(Event.status != "deleted")
            .options(
                selectinload(Event.ranges),
                selectinload(Event.state).selectinload(EventState.factual_range),
                selectinload(Event.state).selectinload(EventState.notified_range),
            )
            .order_by(Event.created_at.desc())
        )
        return result.scalars().all()

    async def create_event(
        self,
        *,
        chat_id: int,
        event_url: str,
        event_title: str,
        source_url: str,
        ended_at: Optional[datetime],
        started_at: Optional[datetime] = None,
        buffer_enabled: bool,
        buffer_percent: float,
        check_interval_minutes: int,
        xtracker_tracking_id: Optional[str] = None,
    ) -> Event:
        event = Event(
            chat_id=chat_id,
            event_url=event_url,
            event_title=event_title,
            source_url=source_url,
            status="active",
            ended_at=ended_at,
            started_at=started_at,
            buffer_enabled=buffer_enabled,
            buffer_percent=buffer_percent,
            check_interval_minutes=check_interval_minutes,
            muted=False,
            xtracker_tracking_id=xtracker_tracking_id,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def deactivate_current_active(self) -> None:
        await self.session.execute(
            update(Event)
            .where(Event.status == "active")
            .values(status="completed", updated_at=datetime.now(timezone.utc))
        )

    async def delete_event(self, event_id: int) -> None:
        await self.session.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(status="deleted", updated_at=datetime.now(timezone.utc))
        )

    async def mark_completed(self, event_id: int) -> None:
        await self.session.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(status="completed", updated_at=datetime.now(timezone.utc))
        )

    # ── Ranges ──────────────────────────────────────────────────────

    async def create_ranges(
        self, event_id: int, ranges: list[tuple[str, int, int]]
    ) -> list[Range]:
        db_ranges: list[Range] = []
        for idx, (label, min_val, max_val) in enumerate(ranges):
            r = Range(
                event_id=event_id,
                label=label,
                min_value=min_val,
                max_value=max_val,
                sort_order=idx,
            )
            self.session.add(r)
            db_ranges.append(r)
        await self.session.flush()
        return db_ranges

    async def get_ranges_for_event(self, event_id: int) -> Sequence[Range]:
        result = await self.session.execute(
            select(Range).where(Range.event_id == event_id).order_by(Range.sort_order)
        )
        return result.scalars().all()

    # ── State ───────────────────────────────────────────────────────

    async def create_state(self, event_id: int) -> EventState:
        state = EventState(event_id=event_id)
        self.session.add(state)
        await self.session.flush()
        return state

    async def get_state(self, event_id: int) -> Optional[EventState]:
        result = await self.session.execute(
            select(EventState)
            .where(EventState.event_id == event_id)
            .options(
                selectinload(EventState.factual_range),
                selectinload(EventState.notified_range),
            )
        )
        return result.scalar_one_or_none()

    # ── Notification log ────────────────────────────────────────────

    async def create_notification(
        self,
        event_id: int,
        tweet_count: Optional[int],
        old_range_id: Optional[int],
        new_range_id: Optional[int],
        direction: str,
        message_text: str,
    ) -> NotificationLog:
        log = NotificationLog(
            event_id=event_id,
            tweet_count=tweet_count,
            old_notified_range_id=old_range_id,
            new_notified_range_id=new_range_id,
            direction=direction,
            message_text=message_text,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def get_recent_notifications(
        self, event_id: int, limit: int = 10
    ) -> Sequence[NotificationLog]:
        result = await self.session.execute(
            select(NotificationLog)
            .where(NotificationLog.event_id == event_id)
            .options(
                selectinload(NotificationLog.old_range),
                selectinload(NotificationLog.new_range),
            )
            .order_by(NotificationLog.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_last_error_notification_time(
        self, event_id: int
    ) -> Optional[datetime]:
        result = await self.session.execute(
            select(NotificationLog.created_at)
            .where(
                NotificationLog.event_id == event_id,
                NotificationLog.direction == "error",
            )
            .order_by(NotificationLog.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
