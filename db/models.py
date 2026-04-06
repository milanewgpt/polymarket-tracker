from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, nullable=False)
    event_url = Column(String, nullable=False)
    event_title = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    ended_at = Column(DateTime, nullable=True)
    buffer_enabled = Column(Boolean, nullable=False, default=True)
    buffer_percent = Column(Float, nullable=False, default=3.0)
    check_interval_minutes = Column(Integer, nullable=False, default=10)
    muted = Column(Boolean, nullable=False, default=False)
    xtracker_tracking_id = Column(String, nullable=True)

    ranges = relationship("Range", back_populates="event", cascade="all, delete-orphan")
    state = relationship(
        "EventState", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    notifications = relationship(
        "NotificationLog", back_populates="event", cascade="all, delete-orphan"
    )


class Range(Base):
    __tablename__ = "ranges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    label = Column(String, nullable=False)
    min_value = Column(Integer, nullable=False)
    max_value = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False)

    event = relationship("Event", back_populates="ranges")


class EventState(Base):
    __tablename__ = "event_state"

    event_id = Column(Integer, ForeignKey("events.id"), primary_key=True)
    current_tweet_count = Column(Integer, nullable=True)
    factual_range_id = Column(Integer, ForeignKey("ranges.id"), nullable=True)
    notified_range_id = Column(Integer, ForeignKey("ranges.id"), nullable=True)
    last_success_check_at = Column(DateTime, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    last_error_message = Column(Text, nullable=True)
    last_notification_at = Column(DateTime, nullable=True)
    last_recovery_at = Column(DateTime, nullable=True)

    event = relationship("Event", back_populates="state")
    factual_range = relationship("Range", foreign_keys=[factual_range_id])
    notified_range = relationship("Range", foreign_keys=[notified_range_id])


class NotificationLog(Base):
    __tablename__ = "notifications_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    tweet_count = Column(Integer, nullable=True)
    old_notified_range_id = Column(Integer, ForeignKey("ranges.id"), nullable=True)
    new_notified_range_id = Column(Integer, ForeignKey("ranges.id"), nullable=True)
    direction = Column(String, nullable=False)
    message_text = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    event = relationship("Event", back_populates="notifications")
    old_range = relationship("Range", foreign_keys=[old_notified_range_id])
    new_range = relationship("Range", foreign_keys=[new_notified_range_id])
