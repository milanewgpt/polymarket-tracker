from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EventStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DELETED = "deleted"


class TransitionDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    NONE = "none"


class NotificationType(str, Enum):
    UP = "up"
    DOWN = "down"
    ERROR = "error"
    RECOVERY = "recovery"
    INFO = "info"


@dataclass(frozen=True)
class RangeEntity:
    id: int
    label: str
    min_value: int
    max_value: int
    sort_order: int

    def __lt__(self, other: RangeEntity) -> bool:
        return self.min_value < other.min_value


@dataclass
class DecisionResult:
    current_factual_range: Optional[RangeEntity]
    should_notify: bool
    new_notified_range: Optional[RangeEntity]
    direction: TransitionDirection
    reason: str
    trigger_threshold: Optional[int] = None
