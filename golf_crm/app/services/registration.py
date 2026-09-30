"""Tournament registration rules: participant limit and waitlist.

Both "applied" and "confirmed" registrations occupy a slot. When the limit is
reached, new applications go to the waitlist automatically. When a slot frees
up (rejection or move to waitlist), the earliest waitlisted player is promoted
to "applied".
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.models import Member, Registration, Tournament
from app.services.leaderboard import assign_category

OCCUPYING = ("applied", "confirmed")


class RegistrationError(ValueError):
    """Business rule violation; the message is shown to the user (Russian)."""


def default_tee(member: Member) -> str:
    return "yellow" if member.gender == "M" else "red"


def register(
    tournament: Tournament,
    member: Member,
    today: date,
    tee: Optional[str] = None,
    enforce_deadline: bool = True,
) -> Registration:
    if tournament.status != "registration":
        raise RegistrationError("Регистрация на этот турнир закрыта.")
    if enforce_deadline and today > tournament.registration_deadline:
        raise RegistrationError("Срок подачи заявок истёк.")
    if any(r.member_id == member.id for r in tournament.registrations):
        raise RegistrationError("Игрок уже подал заявку на этот турнир.")
    if member.status == "suspended":
        raise RegistrationError("Членство игрока приостановлено — заявка невозможна.")
    tee = tee or default_tee(member)
    if tournament.course.tee(tee) is None:
        raise RegistrationError("На этом поле нет выбранных ти.")

    status = "waitlist" if tournament.is_full else "applied"
    reg = Registration(
        member=member,
        member_id=member.id,
        applied_on=today,
        status=status,
        fee_paid=tournament.entry_fee == 0,
        tee=tee,
        category=assign_category(member, tournament.category_codes, tournament.start_date),
    )
    tournament.registrations.append(reg)
    return reg


def first_in_waitlist(tournament: Tournament) -> Optional[Registration]:
    waiting = [r for r in tournament.registrations if r.status == "waitlist"]
    waiting.sort(key=lambda r: (r.applied_on, r.id or 0))
    return waiting[0] if waiting else None


def change_status(reg: Registration, new_status: str) -> Optional[Registration]:
    """Change a registration's status. Returns a registration promoted from the waitlist, if any."""
    tournament = reg.tournament
    if new_status not in ("applied", "confirmed", "waitlist", "rejected"):
        raise RegistrationError("Неизвестный статус заявки.")
    if tournament.status in ("finished", "cancelled"):
        raise RegistrationError("Турнир завершён или отменён — заявки изменить нельзя.")
    if new_status == reg.status:
        return None
    if new_status in OCCUPYING and reg.status not in OCCUPYING and tournament.is_full:
        raise RegistrationError(
            f"Достигнут лимит участников ({tournament.max_participants}). "
            "Сначала освободите место или увеличьте лимит."
        )
    was_occupying = reg.status in OCCUPYING
    reg.status = new_status
    if was_occupying and new_status not in OCCUPYING and tournament.status == "registration":
        candidate = first_in_waitlist(tournament)
        if candidate is not None and candidate is not reg:
            candidate.status = "applied"
            return candidate
    return None


def promote_after_limit_change(tournament: Tournament) -> list[Registration]:
    """After the limit is raised, fill the free slots from the waitlist."""
    promoted = []
    while not tournament.is_full:
        candidate = first_in_waitlist(tournament)
        if candidate is None:
            break
        candidate.status = "applied"
        promoted.append(candidate)
    return promoted
