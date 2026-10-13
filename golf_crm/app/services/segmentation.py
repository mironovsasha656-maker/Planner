"""Recipient segments for mailings.

Only members with a personal data processing consent and an e-mail address
are reachable; the others are reported separately so the operator sees why
they were excluded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.labels import SEGMENTS
from app.models import Club, Member, Payment, Registration, Tournament, age_category


class SegmentError(ValueError):
    pass


@dataclass
class SegmentResult:
    label: str
    recipients: list[Member] = field(default_factory=list)
    no_consent: list[Member] = field(default_factory=list)
    no_email: list[Member] = field(default_factory=list)

    @property
    def total_matched(self) -> int:
        return len(self.recipients) + len(self.no_consent) + len(self.no_email)


def debtor_ids(session: Session, year: int) -> set[int]:
    stmt = select(Payment.member_id).where(
        Payment.type == "membership",
        Payment.period_year == year,
        Payment.status.in_(("pending", "overdue")),
    )
    return set(session.scalars(stmt))


def matching_members(session: Session, segment: str, param: Optional[int], today: date) -> tuple[str, list[Member]]:
    if segment not in SEGMENTS:
        raise SegmentError("Выберите сегмент получателей.")
    label = SEGMENTS[segment]
    stmt = select(Member).order_by(Member.last_name.collate("ru"), Member.first_name)

    if segment == "debtors":
        stmt = stmt.where(Member.id.in_(debtor_ids(session, today.year)))
    elif segment == "club":
        club = session.get(Club, param) if param else None
        if club is None:
            raise SegmentError("Выберите клуб.")
        label = f"{label}: {club.name}"
        stmt = stmt.where(Member.club_id == club.id)
    elif segment == "tournament":
        tournament = session.get(Tournament, param) if param else None
        if tournament is None:
            raise SegmentError("Выберите турнир.")
        label = f"{label}: {tournament.name}"
        stmt = stmt.join(Registration).where(
            Registration.tournament_id == tournament.id,
            Registration.status.in_(("applied", "confirmed")),
        )

    members = list(session.scalars(stmt))
    if segment in ("juniors", "seniors"):
        wanted = segment[:-1]  # "junior" / "senior"
        members = [m for m in members if age_category(m.birth_date, today) == wanted]
    return label, members


def resolve(session: Session, segment: str, param: Optional[int], today: date) -> SegmentResult:
    label, members = matching_members(session, segment, param, today)
    result = SegmentResult(label=label)
    for m in members:
        if not m.pd_consent:
            result.no_consent.append(m)
        elif not m.email:
            result.no_email.append(m)
        else:
            result.recipients.append(m)
    return result
