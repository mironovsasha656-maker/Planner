"""Handicap calculation.

WARNING: this is a SIMPLIFIED DEMO implementation inspired by the World Handicap
System. It is NOT a certified calculation under R&A / USGA rules. Missing parts
include: hole-by-hole net double bogey adjustment, Playing Conditions Calculation
(PCC), soft/hard caps, exceptional score reduction, 9-hole score handling and
the rounding rules of the official implementation.

Formulas used:
  differential = (113 / Slope) * (Adjusted Gross Score - Course Rating)
  index        = average of the best 8 of the most recent 20 differentials,
                 with a reduced table when fewer than 20 rounds exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence
from app import timeutil as msk

MIN_INDEX = 0.0
MAX_INDEX = 54.0
MIN_ROUNDS = 3
WINDOW = 20

# rounds available -> (number of lowest differentials to average, adjustment)
_TABLE: dict[int, tuple[int, float]] = {
    3: (1, -2.0),
    4: (1, -1.0),
    5: (1, 0.0),
    6: (2, -1.0),
    7: (2, 0.0),
    8: (2, 0.0),
    9: (3, 0.0),
    10: (3, 0.0),
    11: (3, 0.0),
    12: (4, 0.0),
    13: (4, 0.0),
    14: (4, 0.0),
    15: (5, 0.0),
    16: (5, 0.0),
    17: (6, 0.0),
    18: (6, 0.0),
    19: (7, 0.0),
    20: (8, 0.0),
}


def round1(value: float) -> float:
    """Round half up to one decimal (Python's round() uses banker's rounding)."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def score_differential(adjusted_gross: int, course_rating: float, slope_rating: int) -> float:
    if slope_rating <= 0:
        raise ValueError("Slope Rating must be positive")
    # Decimal arithmetic avoids float artefacts such as 80 - 71.95 = 8.0499999.
    value = Decimal(113) / Decimal(slope_rating) * (Decimal(adjusted_gross) - Decimal(str(course_rating)))
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def rule_for(rounds_count: int) -> Optional[tuple[int, float]]:
    """How many lowest differentials are averaged and the adjustment applied."""
    if rounds_count < MIN_ROUNDS:
        return None
    return _TABLE[min(rounds_count, WINDOW)]


def handicap_index(differentials: Sequence[float]) -> Optional[float]:
    """Index from differentials given in chronological order (oldest first).

    Returns None when fewer than 3 rounds are available.
    """
    recent = list(differentials)[-WINDOW:]
    rule = rule_for(len(recent))
    if rule is None:
        return None
    count, adjustment = rule
    lowest = sorted(recent)[:count]
    value = sum(lowest) / count + adjustment
    return min(MAX_INDEX, max(MIN_INDEX, round1(round(value, 6))))


def counted_positions(differentials: Sequence[float]) -> set[int]:
    """Indexes (into the given chronological list) of differentials that count."""
    recent_start = max(0, len(differentials) - WINDOW)
    rule = rule_for(len(differentials) - recent_start)
    if rule is None:
        return set()
    recent = sorted(range(recent_start, len(differentials)), key=lambda i: (differentials[i], i))
    return set(recent[: rule[0]])


def course_handicap(index: Optional[float], slope_rating: int, course_rating: float, par: int) -> int:
    """Course handicap = Index * Slope / 113 + (Course Rating - Par), rounded."""
    if index is None:
        index = MAX_INDEX
    value = Decimal(str(index)) * slope_rating / Decimal(113) + (Decimal(str(course_rating)) - par)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class HistoryPoint:
    played_on: date
    index: Optional[float]


def index_history(rounds: Iterable[tuple[date, float]]) -> list[HistoryPoint]:
    """Index after each round; rounds are (date, differential) pairs."""
    ordered = sorted(rounds, key=lambda r: r[0])
    diffs: list[float] = []
    history = []
    for played_on, diff in ordered:
        diffs.append(diff)
        history.append(HistoryPoint(played_on, handicap_index(diffs)))
    return history


def recalculate_member(member) -> Optional[float]:
    """Recompute and store a member's index from their rounds.

    Returns the new index, or None when there are fewer than 3 rounds (the
    manually entered initial index is then kept unchanged).
    """
    ordered = sorted(member.rounds, key=lambda r: (r.played_on, r.id or 0))
    value = handicap_index([r.differential for r in ordered])
    if value is None:
        return None
    member.handicap_index = value
    member.handicap_updated_at = msk.now().replace(microsecond=0)
    return value
