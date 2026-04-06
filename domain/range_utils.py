import re
import sys
from typing import Optional

from domain.entities import RangeEntity


def find_range_for_count(count: int, ranges: list[RangeEntity]) -> Optional[RangeEntity]:
    """Return the range that contains *count*, or None."""
    for r in ranges:
        if r.min_value <= count <= r.max_value:
            return r
    return None


def get_next_range(
    current_range: Optional[RangeEntity], ranges: list[RangeEntity]
) -> Optional[RangeEntity]:
    """Return the range immediately above *current_range*."""
    if current_range is None:
        return ranges[0] if ranges else None
    for r in ranges:
        if r.min_value > current_range.max_value:
            return r
    return None


def parse_range_label(label: str) -> tuple[int, int]:
    """
    Parse labels such as '50-100', '200+', 'Under 50' into (min, max).
    Raises ValueError on unparseable input.
    """
    label = label.strip()

    m = re.match(r"^(\d+)\s*\+$", label)
    if m:
        return int(m.group(1)), sys.maxsize

    m = re.match(r"^(\d+)\s*[-\u2013\u2014]\s*(\d+)$", label)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.match(
        r"^(?:under|less than|fewer than|<)\s*(\d+)$", label, re.IGNORECASE
    )
    if m:
        return 0, int(m.group(1)) - 1

    raise ValueError(f"Cannot parse range label: {label}")


def extract_range_from_text(text: str) -> Optional[str]:
    """Pull a range token out of free-form text (market title, question, etc.)."""
    m = re.search(r"(\d+)\s*[-\u2013\u2014]\s*(\d+)", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    m = re.search(r"(\d+)\s*\+", text)
    if m:
        return f"{m.group(1)}+"

    m = re.search(r"(?:under|less than|fewer than|<)\s*(\d+)", text, re.IGNORECASE)
    if m:
        return f"Under {m.group(1)}"

    return None
