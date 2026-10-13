from datetime import date

import pytest

from app.models import Tournament
from app.services.registration import RegistrationError, change_status, promote_after_limit_change, register

TODAY = date(2026, 5, 1)


@pytest.fixture
def tournament(session, course):
    t = Tournament(name="Кубок", start_date=date(2026, 6, 1), end_date=date(2026, 6, 1), course=course,
                   format="stroke_gross", categories="men,women", rounds_count=1, entry_fee=3000,
                   max_participants=2, registration_deadline=date(2026, 5, 25), status="registration")
    session.add(t)
    session.flush()
    return t


def test_registrations_within_limit_are_applied(tournament, member_factory):
    r1 = register(tournament, member_factory(), TODAY)
    r2 = register(tournament, member_factory(gender="F"), TODAY)
    assert (r1.status, r2.status) == ("applied", "applied")
    assert r2.tee == "red"
    assert r2.category == "women"
    assert not r1.fee_paid


def test_over_limit_goes_to_waitlist(tournament, member_factory):
    register(tournament, member_factory(), TODAY)
    register(tournament, member_factory(), TODAY)
    r3 = register(tournament, member_factory(), TODAY)
    assert r3.status == "waitlist"
    assert tournament.occupied == 2
    assert tournament.waitlist_count == 1


def test_duplicate_registration_rejected(tournament, member_factory):
    m = member_factory()
    register(tournament, m, TODAY)
    with pytest.raises(RegistrationError):
        register(tournament, m, TODAY)


def test_closed_registration_and_deadline(tournament, member_factory):
    with pytest.raises(RegistrationError, match="Срок"):
        register(tournament, member_factory(), date(2026, 5, 26))
    tournament.status = "draft"
    with pytest.raises(RegistrationError, match="закрыта"):
        register(tournament, member_factory(), TODAY)


def test_suspended_member_cannot_register(tournament, member_factory):
    with pytest.raises(RegistrationError):
        register(tournament, member_factory(status="suspended"), TODAY)


def test_cannot_confirm_waitlisted_when_full(tournament, member_factory):
    register(tournament, member_factory(), TODAY)
    register(tournament, member_factory(), TODAY)
    waiting = register(tournament, member_factory(), TODAY)
    with pytest.raises(RegistrationError, match="лимит"):
        change_status(waiting, "confirmed")


def test_rejecting_frees_slot_and_promotes_waitlist(tournament, member_factory):
    r1 = register(tournament, member_factory(), TODAY)
    register(tournament, member_factory(), TODAY)
    w1 = register(tournament, member_factory(), date(2026, 5, 2))
    w2 = register(tournament, member_factory(), date(2026, 5, 3))
    promoted = change_status(r1, "rejected")
    assert promoted is w1
    assert w1.status == "applied"
    assert w2.status == "waitlist"
    assert tournament.occupied == 2


def test_confirm_within_limit(tournament, member_factory):
    r1 = register(tournament, member_factory(), TODAY)
    assert change_status(r1, "confirmed") is None
    assert r1.status == "confirmed"


def test_raising_limit_promotes_from_waitlist(tournament, member_factory):
    for _ in range(4):
        register(tournament, member_factory(), TODAY)
    tournament.max_participants = 3
    promoted = promote_after_limit_change(tournament)
    assert len(promoted) == 1
    assert tournament.occupied == 3 and tournament.waitlist_count == 1


def test_finished_tournament_is_locked(tournament, member_factory):
    r1 = register(tournament, member_factory(), TODAY)
    tournament.status = "finished"
    with pytest.raises(RegistrationError):
        change_status(r1, "rejected")
