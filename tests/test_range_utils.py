"""Unit tests for range parsing and lookup utilities."""

import sys

import pytest

from domain.entities import RangeEntity
from domain.range_utils import (
    extract_range_from_text,
    find_range_for_count,
    get_next_range,
    parse_range_label,
)


# ── parse_range_label ──────────────────────────────────────────────


class TestParseRangeLabel:
    def test_simple(self):
        assert parse_range_label("50-100") == (50, 100)

    def test_spaces(self):
        assert parse_range_label("50 - 100") == (50, 100)

    def test_en_dash(self):
        assert parse_range_label("50\u2013100") == (50, 100)

    def test_em_dash(self):
        assert parse_range_label("50\u2014100") == (50, 100)

    def test_plus(self):
        mn, mx = parse_range_label("200+")
        assert mn == 200
        assert mx == sys.maxsize

    def test_plus_with_space(self):
        mn, mx = parse_range_label("200 +")
        assert mn == 200

    def test_under(self):
        assert parse_range_label("Under 50") == (0, 49)

    def test_less_than(self):
        assert parse_range_label("Less than 50") == (0, 49)

    def test_fewer_than(self):
        assert parse_range_label("fewer than 50") == (0, 49)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_range_label("banana")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_range_label("")


# ── find_range_for_count ───────────────────────────────────────────


def _two_ranges() -> list[RangeEntity]:
    return [
        RangeEntity(id=1, label="50-100", min_value=50, max_value=100, sort_order=0),
        RangeEntity(id=2, label="101-150", min_value=101, max_value=150, sort_order=1),
    ]


class TestFindRange:
    def test_exact_min(self):
        assert find_range_for_count(50, _two_ranges()) is not None
        assert find_range_for_count(50, _two_ranges()).id == 1  # type: ignore[union-attr]

    def test_exact_max(self):
        assert find_range_for_count(100, _two_ranges()) is not None
        assert find_range_for_count(100, _two_ranges()).id == 1  # type: ignore[union-attr]

    def test_boundary_101(self):
        assert find_range_for_count(101, _two_ranges()) is not None
        assert find_range_for_count(101, _two_ranges()).id == 2  # type: ignore[union-attr]

    def test_mid_range(self):
        assert find_range_for_count(75, _two_ranges()) is not None
        assert find_range_for_count(75, _two_ranges()).id == 1  # type: ignore[union-attr]

    def test_none_below(self):
        assert find_range_for_count(10, _two_ranges()) is None

    def test_none_above(self):
        assert find_range_for_count(200, _two_ranges()) is None


# ── get_next_range ─────────────────────────────────────────────────


class TestGetNextRange:
    def test_has_next(self):
        ranges = _two_ranges()
        nxt = get_next_range(ranges[0], ranges)
        assert nxt is not None
        assert nxt.id == 2

    def test_no_next(self):
        ranges = _two_ranges()
        assert get_next_range(ranges[1], ranges) is None

    def test_none_input(self):
        ranges = _two_ranges()
        nxt = get_next_range(None, ranges)
        assert nxt is not None
        assert nxt.id == 1

    def test_empty_ranges(self):
        assert get_next_range(None, []) is None


# ── extract_range_from_text ────────────────────────────────────────


class TestExtractRange:
    def test_in_sentence(self):
        assert extract_range_from_text("Will there be 50-100 tweets?") == "50-100"

    def test_plus(self):
        assert extract_range_from_text("200+ tweets possible") == "200+"

    def test_under(self):
        assert extract_range_from_text("Under 50 tweets") == "Under 50"

    def test_no_match(self):
        assert extract_range_from_text("No range here") is None

    def test_en_dash(self):
        assert extract_range_from_text("101\u2013150") == "101-150"
