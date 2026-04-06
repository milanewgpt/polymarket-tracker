"""Telegram message formatting — pure functions, no I/O."""

from typing import Optional, Sequence

from db.models import Event, EventState, NotificationLog, Range as RangeModel
from domain.entities import RangeEntity
from domain.range_utils import get_next_range


def format_event_summary(
    event: Event,
    ranges: list[RangeModel],
    tweet_count: Optional[int],
    factual_range: Optional[RangeModel],
    next_range: Optional[RangeModel],
) -> str:
    buffer_mode = "ON" if event.buffer_enabled else "OFF"
    lines = [
        "\u2705 <b>Event added</b>\n",
        f"\U0001f4cc {event.event_title}",
        f'\U0001f517 <a href="{event.event_url}">Event link</a>',
        f"\U0001f4ca Ranges found: {len(ranges)}",
    ]
    if tweet_count is not None:
        lines.append(f"\U0001f426 Current tweets: {tweet_count}")
    if factual_range:
        lines.append(f"\U0001f4cd Current range: {factual_range.label}")
    if next_range:
        lines.append(f"\u27a1\ufe0f Next range: {next_range.label}")
    lines.extend(
        [
            f"\U0001f527 Buffer: {buffer_mode} ({event.buffer_percent}%)",
            f"\u23f1\ufe0f Check interval: {event.check_interval_minutes} min",
            f"\U0001f514 Notifications: {'muted' if event.muted else 'enabled'}",
        ]
    )
    return "\n".join(lines)


def format_status(
    event: Event, state: Optional[EventState], ranges: list[RangeModel]
) -> str:
    range_entities = _to_entities(ranges)
    buffer_mode = "ON" if event.buffer_enabled else "OFF"
    factual_label = "\u2014"
    notified_label = "\u2014"
    next_label = "\u2014"
    tweet_count_text = "\u2014"

    if state:
        if state.current_tweet_count is not None:
            tweet_count_text = str(state.current_tweet_count)
        if state.factual_range:
            factual_label = state.factual_range.label
            fe = _find_entity(range_entities, state.factual_range_id)
            nr = get_next_range(fe, range_entities)
            if nr:
                next_label = nr.label
        if state.notified_range:
            notified_label = state.notified_range.label

    source_health = "\u2705 OK"
    last_check = "\u2014"
    if state:
        _err = state.last_error_at
        _rec = state.last_recovery_at
        if _err and (_rec is None or _rec < _err):
            source_health = f"\u274c Error: {state.last_error_message or 'unknown'}"
        if state.last_success_check_at:
            last_check = state.last_success_check_at.strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"\U0001f4ca <b>Status</b>\n\n"
        f"\U0001f4cc {event.event_title}\n"
        f'\U0001f517 <a href="{event.event_url}">Event</a>\n'
        f"\U0001f426 Tweets: {tweet_count_text}\n"
        f"\U0001f4cd Factual range: {factual_label}\n"
        f"\U0001f514 Notified range: {notified_label}\n"
        f"\u27a1\ufe0f Next range: {next_label}\n"
        f"\U0001f527 Buffer: {buffer_mode} ({event.buffer_percent}%)\n"
        f"\u23f1\ufe0f Interval: {event.check_interval_minutes} min\n"
        f"\U0001f507 Muted: {'yes' if event.muted else 'no'}\n"
        f"\U0001f49a Source: {source_health}\n"
        f"\U0001f550 Last check: {last_check}"
    )


def format_count(
    event: Event, state: Optional[EventState], ranges: list[RangeModel]
) -> str:
    range_entities = _to_entities(ranges)
    tweet_count_text = "\u2014"
    factual_label = "\u2014"
    next_label = "\u2014"

    if state and state.current_tweet_count is not None:
        tweet_count_text = str(state.current_tweet_count)
        fe = _find_entity(range_entities, state.factual_range_id)
        if fe:
            factual_label = fe.label
            nr = get_next_range(fe, range_entities)
            if nr:
                next_label = nr.label

    return (
        f"\U0001f426 Tweets: <b>{tweet_count_text}</b>\n"
        f"\U0001f4cd Range: {factual_label}\n"
        f"\u27a1\ufe0f Next: {next_label}\n"
        f'\U0001f517 <a href="{event.event_url}">Event</a>'
    )


def format_list(events: Sequence[Event]) -> str:
    if not events:
        return "No tracked events."

    lines = ["<b>Tracked Events</b>\n"]
    for ev in events:
        icon = {"active": "\U0001f7e2", "completed": "\u2705"}.get(ev.status, "\u26aa")
        mute_tag = " \U0001f507" if ev.muted else ""
        extra = ""
        if ev.state:
            if ev.state.current_tweet_count is not None:
                extra += f"\n   Tweets: {ev.state.current_tweet_count}"
            if ev.state.factual_range:
                extra += f"\n   Factual: {ev.state.factual_range.label}"
            if ev.state.notified_range:
                extra += f"\n   Notified: {ev.state.notified_range.label}"
        lines.append(
            f"{icon} <b>{ev.event_title}</b>{mute_tag}\n"
            f"   Status: {ev.status}{extra}\n"
            f'   <a href="{ev.event_url}">link</a>'
        )
    return "\n\n".join(lines)


def format_history(logs: Sequence[NotificationLog]) -> str:
    if not logs:
        return "No transition history."

    direction_icons = {
        "up": "\U0001f4c8",
        "down": "\U0001f4c9",
        "error": "\u26a0\ufe0f",
        "recovery": "\u2705",
        "info": "\u2139\ufe0f",
    }
    lines = ["<b>Last transitions</b>\n"]
    for log in logs:
        icon = direction_icons.get(log.direction, "\u2022")
        ts = log.created_at.strftime("%m-%d %H:%M") if log.created_at else "?"
        old_label = log.old_range.label if log.old_range else "\u2014"
        new_label = log.new_range.label if log.new_range else "\u2014"
        tweet_text = str(log.tweet_count) if log.tweet_count is not None else "\u2014"
        lines.append(
            f"{icon} {ts} | tweets: {tweet_text} | "
            f"{old_label} \u2192 {new_label} ({log.direction})"
        )
    return "\n".join(lines)


# ── Internal helpers ────────────────────────────────────────────────


def _to_entities(db_ranges: list[RangeModel]) -> list[RangeEntity]:
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


def _find_entity(
    entities: list[RangeEntity], range_id: Optional[int]
) -> Optional[RangeEntity]:
    if range_id is None:
        return None
    for e in entities:
        if e.id == range_id:
            return e
    return None
