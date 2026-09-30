from datetime import date

import pytest

from app.models import Club, Payment, Registration, Tournament
from app.services.segmentation import SegmentError, resolve

TODAY = date(2026, 6, 1)


@pytest.fixture
def world(session, course, member_factory):
    other_club = Club(name="Второй клуб", district="—", address="—", contact_person="—", phone="—", holes=9)
    session.add(other_club)
    session.flush()
    club = course.club
    adult = member_factory(club=club)
    junior = member_factory(club=club, birth=date(2012, 3, 1))
    senior = member_factory(club=other_club, birth=date(1955, 3, 1))
    no_consent = member_factory(club=other_club, consent=False)
    no_email = member_factory(club=club, email="")
    for m, status in ((adult, "overdue"), (junior, "paid"), (senior, "pending"), (no_consent, "overdue")):
        session.add(Payment(member=m, type="membership", amount=5000, issued_on=date(2026, 1, 15),
                            due_date=date(2026, 2, 14), method="invoice", status=status, period_year=2026))
    t = Tournament(name="Турнир", start_date=date(2026, 7, 1), end_date=date(2026, 7, 1), course=course,
                   format="stroke_gross", categories="men", rounds_count=1, entry_fee=0,
                   max_participants=10, registration_deadline=date(2026, 6, 25), status="registration")
    t.registrations = [
        Registration(member=adult, applied_on=TODAY, status="confirmed", tee="yellow"),
        Registration(member=senior, applied_on=TODAY, status="waitlist", tee="yellow"),
        Registration(member=junior, applied_on=TODAY, status="applied", tee="yellow"),
    ]
    session.add(t)
    session.flush()
    return dict(club=club, other_club=other_club, adult=adult, junior=junior, senior=senior,
                no_consent=no_consent, no_email=no_email, tournament=t)


def test_all_excludes_no_consent_and_no_email(session, world):
    res = resolve(session, "all", None, TODAY)
    assert set(res.recipients) == {world["adult"], world["junior"], world["senior"]}
    assert res.no_consent == [world["no_consent"]]
    assert res.no_email == [world["no_email"]]
    assert res.total_matched == 5


def test_debtors(session, world):
    res = resolve(session, "debtors", None, TODAY)
    assert set(res.recipients) == {world["adult"], world["senior"]}
    assert res.no_consent == [world["no_consent"]]


def test_age_segments(session, world):
    assert resolve(session, "juniors", None, TODAY).recipients == [world["junior"]]
    assert resolve(session, "seniors", None, TODAY).recipients == [world["senior"]]


def test_club_segment(session, world):
    res = resolve(session, "club", world["club"].id, TODAY)
    assert set(res.recipients) == {world["adult"], world["junior"]}
    assert world["club"].name in res.label


def test_tournament_segment_excludes_waitlist(session, world):
    res = resolve(session, "tournament", world["tournament"].id, TODAY)
    assert set(res.recipients) == {world["adult"], world["junior"]}


def test_invalid_segments(session, world):
    with pytest.raises(SegmentError):
        resolve(session, "unknown", None, TODAY)
    with pytest.raises(SegmentError):
        resolve(session, "club", None, TODAY)
    with pytest.raises(SegmentError):
        resolve(session, "tournament", 9999, TODAY)
