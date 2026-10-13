"""Tournament totals, positions and leaderboards.

Stableford points are estimated from round totals because the demo stores no
hole-by-hole scores: points = max(0, 36 + par + course handicap - gross)
per 18-hole round (i.e. net par = 36 points, one point per stroke).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Hashable, Iterable, Optional, Sequence, TypeVar

from app.models import Member, Registration, Result, Tournament, age_category
from app.services import handicap

T = TypeVar("T")

LOWER_IS_BETTER = {"stroke_gross": True, "stroke_net": True, "stableford": False}


def assign_category(member: Member, categories: Sequence[str], on: date) -> str:
    """Pick the scoring category for a player: juniors, seniors, then gender."""
    age_cat = age_category(member.birth_date, on)
    if age_cat == "junior" and "juniors" in categories:
        return "juniors"
    if age_cat == "senior" and "seniors" in categories:
        return "seniors"
    gender_cat = "men" if member.gender == "M" else "women"
    if gender_cat in categories:
        return gender_cat
    return ""


def stableford_points(gross: int, par: int, course_handicap: int) -> int:
    return max(0, 36 + par + course_handicap - gross)


@dataclass
class Totals:
    rounds_played: int
    total_gross: Optional[int]
    total_net: Optional[int]
    stableford_points: Optional[int]


def compute_totals(scores: Sequence[Optional[int]], rounds_count: int, par: int, course_hcp: int) -> Totals:
    played = [s for s in list(scores)[:rounds_count] if s is not None]
    if not played:
        return Totals(0, None, None, None)
    gross = sum(played)
    return Totals(
        rounds_played=len(played),
        total_gross=gross,
        total_net=gross - course_hcp * len(played),
        stableford_points=sum(stableford_points(s, par, course_hcp) for s in played),
    )


def rank(items: Iterable[T], key: Callable[[T], Hashable]) -> dict[int, int]:
    """Standard competition ranking ("1, 2, 2, 4"). Returns {id(item): position}."""
    ordered = sorted(items, key=key)
    positions: dict[int, int] = {}
    prev_key = object()
    prev_pos = 0
    for i, item in enumerate(ordered, start=1):
        k = key(item)
        pos = prev_pos if k == prev_key else i
        positions[id(item)] = pos
        prev_key, prev_pos = k, pos
    return positions


def metric(result: Result, fmt: str) -> Optional[int]:
    if fmt == "stroke_gross":
        return result.total_gross
    if fmt == "stroke_net":
        return result.total_net
    return result.stableford_points


def sort_key(fmt: str) -> Callable[[Result], tuple]:
    lower = LOWER_IS_BETTER[fmt]

    def key(result: Result) -> tuple:
        value = metric(result, fmt) or 0
        # More rounds played ranks first (relevant while a tournament is in progress).
        return (-result.rounds_played, value if lower else -value)

    return key


def tee_for(tournament: Tournament, reg: Registration):
    tee = tournament.course.tee(reg.tee)
    if tee is None:
        tee = tournament.course.tees[0]
    return tee


def recalculate(tournament: Tournament) -> None:
    """Recompute totals and positions of every result of the tournament."""
    results = []
    for reg in tournament.registrations:
        res = reg.result
        if res is None:
            continue
        if reg.status != "confirmed":
            continue
        tee = tee_for(tournament, reg)
        totals = compute_totals(res.scores, tournament.rounds_count, tee.par, res.course_handicap)
        res.rounds_played = totals.rounds_played
        res.total_gross = totals.total_gross
        res.total_net = totals.total_net
        res.stableford_points = totals.stableford_points
        res.position = None
        res.category_position = None
        if totals.rounds_played:
            results.append(res)

    key = sort_key(tournament.format)
    overall = rank(results, key)
    for res in results:
        res.position = overall[id(res)]

    by_cat: dict[str, list[Result]] = {}
    for res in results:
        cat = res.registration.category
        if cat:
            by_cat.setdefault(cat, []).append(res)
    for group in by_cat.values():
        positions = rank(group, key)
        for res in group:
            res.category_position = positions[id(res)]


def ensure_result(tournament: Tournament, reg: Registration) -> Result:
    """Create an empty result with the course handicap fixed at entry time."""
    if reg.result is None:
        tee = tee_for(tournament, reg)
        reg.result = Result(
            course_handicap=handicap.course_handicap(
                reg.member.handicap_index, tee.slope_rating, tee.course_rating, tee.par
            )
        )
    return reg.result


@dataclass
class Row:
    position: Optional[int]
    tied: bool
    registration: Registration
    result: Result
    scores: list[Optional[int]]
    to_par: Optional[int]


@dataclass
class Board:
    title: str
    rows: list[Row] = field(default_factory=list)


def _rows(tournament: Tournament, results: list[Result], use_category: bool) -> list[Row]:
    pos_attr = "category_position" if use_category else "position"
    ranked = [r for r in results if getattr(r, pos_attr) is not None]
    ranked.sort(key=lambda r: (getattr(r, pos_attr), r.registration.member.last_name))
    counts: dict[int, int] = {}
    for r in ranked:
        counts[getattr(r, pos_attr)] = counts.get(getattr(r, pos_attr), 0) + 1
    rows = []
    for r in ranked:
        tee = tee_for(tournament, r.registration)
        par_total = tee.par * r.rounds_played
        score = r.total_net if tournament.format == "stroke_net" else r.total_gross
        rows.append(
            Row(
                position=getattr(r, pos_attr),
                tied=counts[getattr(r, pos_attr)] > 1,
                registration=r.registration,
                result=r,
                scores=r.scores[: tournament.rounds_count],
                to_par=(score - par_total) if score is not None else None,
            )
        )
    return rows


def boards(tournament: Tournament) -> tuple[Board, list[Board]]:
    """Overall board plus one board per scoring category."""
    from app.labels import SCORING_CATEGORY

    results = [
        reg.result
        for reg in tournament.registrations
        if reg.status == "confirmed" and reg.result is not None
    ]
    overall = Board("Общий зачёт", _rows(tournament, results, False))
    cats = []
    for code in tournament.category_codes:
        group = [r for r in results if r.registration.category == code]
        if group:
            cats.append(Board(SCORING_CATEGORY.get(code, code), _rows(tournament, group, True)))
    return overall, cats
