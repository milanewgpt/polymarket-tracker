"""Unit tests for the pure decision engine — no I/O required."""

import sys

import pytest

from domain.decision_engine import evaluate_transition
from domain.entities import DecisionResult, RangeEntity, TransitionDirection


def _ranges() -> list[RangeEntity]:
    return [
        RangeEntity(id=1, label="0-49", min_value=0, max_value=49, sort_order=0),
        RangeEntity(id=2, label="50-100", min_value=50, max_value=100, sort_order=1),
        RangeEntity(id=3, label="101-150", min_value=101, max_value=150, sort_order=2),
        RangeEntity(id=4, label="151-200", min_value=151, max_value=200, sort_order=3),
        RangeEntity(id=5, label="200+", min_value=201, max_value=sys.maxsize, sort_order=4),
    ]


# ── Initial state ──────────────────────────────────────────────────


class TestInitialState:
    def test_sets_factual_and_notified_no_notification(self):
        r = evaluate_transition(75, _ranges(), None, None, True, 3.0)
        assert r.current_factual_range is not None
        assert r.current_factual_range.id == 2
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 2
        assert r.should_notify is False
        assert r.direction == TransitionDirection.NONE

    def test_initial_zero(self):
        r = evaluate_transition(0, _ranges(), None, None, True, 3.0)
        assert r.current_factual_range is not None
        assert r.current_factual_range.id == 1
        assert r.should_notify is False


# ── No change ──────────────────────────────────────────────────────


class TestNoChange:
    def test_same_range(self):
        ranges = _ranges()
        r2 = ranges[1]
        r = evaluate_transition(80, ranges, r2, r2, True, 3.0)
        assert r.should_notify is False
        assert r.direction == TransitionDirection.NONE

    def test_anti_duplicate(self):
        """Ensure repeated identical counts never re-trigger."""
        ranges = _ranges()
        r3 = ranges[2]
        r = evaluate_transition(120, ranges, r3, r3, True, 3.0)
        assert r.should_notify is False


# ── Upward transition — buffer OFF ─────────────────────────────────


class TestUpwardBufferOff:
    def test_immediate_notify(self):
        ranges = _ranges()
        r2 = ranges[1]
        r = evaluate_transition(101, ranges, r2, r2, False, 3.0)
        assert r.should_notify is True
        assert r.direction == TransitionDirection.UP
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 3


# ── Upward transition — buffer ON ──────────────────────────────────


class TestUpwardBufferOn:
    def test_below_threshold_deferred(self):
        ranges = _ranges()
        r2 = ranges[1]
        # threshold for 101-150 = ceil(101 * 1.03) = ceil(104.03) = 105
        r = evaluate_transition(102, ranges, r2, r2, True, 3.0)
        assert r.should_notify is False
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 2  # stays on old range
        assert r.current_factual_range is not None
        assert r.current_factual_range.id == 3  # factual already moved
        assert r.trigger_threshold == 105

    def test_at_threshold_triggers(self):
        ranges = _ranges()
        r2 = ranges[1]
        r = evaluate_transition(105, ranges, r2, r2, True, 3.0)
        assert r.should_notify is True
        assert r.direction == TransitionDirection.UP
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 3
        assert r.trigger_threshold == 105

    def test_above_threshold_triggers(self):
        ranges = _ranges()
        r2 = ranges[1]
        r = evaluate_transition(130, ranges, r2, r2, True, 3.0)
        assert r.should_notify is True
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 3

    def test_multi_range_jump(self):
        """Jump from 50-100 straight into 151-200."""
        ranges = _ranges()
        r2 = ranges[1]
        # threshold = ceil(151 * 1.03) = ceil(155.53) = 156
        r = evaluate_transition(160, ranges, r2, r2, True, 3.0)
        assert r.should_notify is True
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 4
        assert r.trigger_threshold == 156


# ── Downward transition ────────────────────────────────────────────


class TestDownward:
    def test_immediate_downward(self):
        ranges = _ranges()
        r3 = ranges[2]
        r = evaluate_transition(100, ranges, r3, r3, True, 3.0)
        assert r.should_notify is True
        assert r.direction == TransitionDirection.DOWN
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 2

    def test_downward_ignores_buffer(self):
        ranges = _ranges()
        r3 = ranges[2]
        r = evaluate_transition(99, ranges, r3, r3, True, 10.0)
        assert r.should_notify is True
        assert r.direction == TransitionDirection.DOWN

    def test_source_correction_big_drop(self):
        ranges = _ranges()
        r3 = ranges[2]
        r = evaluate_transition(50, ranges, r3, r3, True, 3.0)
        assert r.should_notify is True
        assert r.direction == TransitionDirection.DOWN
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 2


# ── Buffer zone → then threshold reached ───────────────────────────


class TestBufferZoneSequence:
    def test_two_step_transition(self):
        ranges = _ranges()
        r2 = ranges[1]

        # Step 1: enters buffer zone
        res1 = evaluate_transition(102, ranges, r2, r2, True, 3.0)
        assert res1.should_notify is False
        assert res1.current_factual_range is not None
        assert res1.current_factual_range.id == 3
        assert res1.new_notified_range is not None
        assert res1.new_notified_range.id == 2

        # Step 2: reaches threshold — use previous notified_range
        res2 = evaluate_transition(
            105, ranges, res1.current_factual_range, res1.new_notified_range, True, 3.0
        )
        assert res2.should_notify is True
        assert res2.new_notified_range is not None
        assert res2.new_notified_range.id == 3


# ── Edge cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_count_outside_all_ranges(self):
        ranges = [
            RangeEntity(id=1, label="50-100", min_value=50, max_value=100, sort_order=0),
        ]
        r = evaluate_transition(30, ranges, None, None, True, 3.0)
        assert r.current_factual_range is None
        assert r.should_notify is False

    def test_count_outside_after_notified(self):
        ranges = [
            RangeEntity(id=1, label="50-100", min_value=50, max_value=100, sort_order=0),
        ]
        r1 = ranges[0]
        r = evaluate_transition(30, ranges, r1, r1, True, 3.0)
        assert r.current_factual_range is None
        assert r.should_notify is False
        assert r.new_notified_range is not None
        assert r.new_notified_range.id == 1  # stays at last notified

    def test_zero_buffer_percent(self):
        ranges = _ranges()
        r2 = ranges[1]
        # threshold = ceil(101 * 1.00) = 101 — triggers immediately
        r = evaluate_transition(101, ranges, r2, r2, True, 0.0)
        assert r.should_notify is True
        assert r.trigger_threshold == 101
