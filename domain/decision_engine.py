"""
Pure decision engine — no I/O, no side effects, fully testable.

Input:  current tweet count, sorted ranges, previous state, buffer config.
Output: DecisionResult describing what happened and whether to notify.
"""

import math
from typing import Optional

from domain.entities import DecisionResult, RangeEntity, TransitionDirection
from domain.range_utils import find_range_for_count


def evaluate_transition(
    current_tweet_count: int,
    ranges: list[RangeEntity],
    previous_factual_range: Optional[RangeEntity],
    previous_notified_range: Optional[RangeEntity],
    buffer_enabled: bool,
    buffer_percent: float,
) -> DecisionResult:
    current_factual = find_range_for_count(current_tweet_count, ranges)

    if current_factual is None:
        return DecisionResult(
            current_factual_range=None,
            should_notify=False,
            new_notified_range=previous_notified_range,
            direction=TransitionDirection.NONE,
            reason="Tweet count outside all known ranges",
        )

    # Initial state — set both factual and notified, no notification
    if previous_notified_range is None:
        return DecisionResult(
            current_factual_range=current_factual,
            should_notify=False,
            new_notified_range=current_factual,
            direction=TransitionDirection.NONE,
            reason="Initial state",
        )

    # Same range as already notified — nothing to do
    if current_factual.id == previous_notified_range.id:
        return DecisionResult(
            current_factual_range=current_factual,
            should_notify=False,
            new_notified_range=previous_notified_range,
            direction=TransitionDirection.NONE,
            reason="No range change",
        )

    is_upward = current_factual.min_value > previous_notified_range.min_value

    if is_upward:
        if not buffer_enabled:
            return DecisionResult(
                current_factual_range=current_factual,
                should_notify=True,
                new_notified_range=current_factual,
                direction=TransitionDirection.UP,
                reason="Upward transition (buffer OFF)",
            )

        trigger = math.ceil(
            current_factual.min_value * (1 + buffer_percent / 100)
        )

        if current_tweet_count >= trigger:
            return DecisionResult(
                current_factual_range=current_factual,
                should_notify=True,
                new_notified_range=current_factual,
                direction=TransitionDirection.UP,
                reason=f"Upward transition (buffer ON, threshold={trigger})",
                trigger_threshold=trigger,
            )

        # In buffer zone — factual moved up but notification deferred
        return DecisionResult(
            current_factual_range=current_factual,
            should_notify=False,
            new_notified_range=previous_notified_range,
            direction=TransitionDirection.NONE,
            reason=f"In buffer zone (count={current_tweet_count}, threshold={trigger})",
            trigger_threshold=trigger,
        )

    # Downward — always immediate regardless of buffer
    return DecisionResult(
        current_factual_range=current_factual,
        should_notify=True,
        new_notified_range=current_factual,
        direction=TransitionDirection.DOWN,
        reason="Downward transition (immediate)",
    )
