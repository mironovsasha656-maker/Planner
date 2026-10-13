"""Tournament lifecycle helpers."""
from __future__ import annotations

from datetime import timedelta

from app.models import Member, Round, Tournament
from app.services import handicap, leaderboard

# Allowed manual status transitions (UI buttons).
TRANSITIONS = {
    "draft": ["registration", "cancelled"],
    "registration": ["in_progress", "draft", "cancelled"],
    "in_progress": ["finished", "registration"],
    "finished": [],
    "cancelled": ["draft"],
}


def round_date(tournament: Tournament, round_no: int):
    day = tournament.start_date + timedelta(days=round_no - 1)
    return min(day, tournament.end_date)


def post_rounds_to_handicap(tournament: Tournament) -> list[Member]:
    """Create handicap rounds from tournament scores (once per score). Returns affected members."""
    affected: dict[int, Member] = {}
    for reg in tournament.registrations:
        res = reg.result
        if reg.status != "confirmed" or res is None:
            continue
        tee = leaderboard.tee_for(tournament, reg)
        posted = {r.round_no for r in reg.member.rounds if r.result_id == res.id}
        for i, score in enumerate(res.scores[: tournament.rounds_count], start=1):
            if score is None or i in posted:
                continue
            reg.member.rounds.append(
                Round(
                    tee_id=tee.id,
                    tee=tee,
                    played_on=round_date(tournament, i),
                    adjusted_gross=score,
                    differential=handicap.score_differential(score, tee.course_rating, tee.slope_rating),
                    result_id=res.id,
                    round_no=i,
                )
            )
            affected[reg.member.id] = reg.member
    return list(affected.values())
