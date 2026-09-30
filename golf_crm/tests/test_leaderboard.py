from datetime import date

from sqlalchemy.orm import object_session

from app.models import Registration, Result, Tournament
from app.services import leaderboard as lb


def test_rank_competition_style():
    items = [("a", 70), ("b", 72), ("c", 72), ("d", 75)]
    pos = lb.rank(items, key=lambda x: x[1])
    assert [pos[id(i)] for i in items] == [1, 2, 2, 4]


def test_compute_totals_gross_net_stableford():
    t = lb.compute_totals([80, 84, None, None], rounds_count=2, par=72, course_hcp=10)
    assert t.rounds_played == 2
    assert t.total_gross == 164
    assert t.total_net == 144
    # round 1: 36 + 72 + 10 - 80 = 38; round 2: 36 + 72 + 10 - 84 = 34
    assert t.stableford_points == 72


def test_compute_totals_ignores_rounds_beyond_format():
    t = lb.compute_totals([80, 84, 90, None], rounds_count=1, par=72, course_hcp=0)
    assert t.total_gross == 80


def test_stableford_points_never_negative():
    assert lb.stableford_points(150, 72, 0) == 0


def _tournament(session, course, fmt, rounds=1, categories="men,women"):
    t = Tournament(name="Тест", start_date=date(2026, 6, 1), end_date=date(2026, 6, 1), course=course,
                   format=fmt, categories=categories, rounds_count=rounds, entry_fee=0, max_participants=10,
                   registration_deadline=date(2026, 5, 25), status="in_progress")
    session.add(t)
    return t


def _enter(t, member, hcp, scores, category="men"):
    reg = Registration(tournament=t, member=member, applied_on=date(2026, 5, 1), status="confirmed", tee="yellow",
                       category=category)
    reg.result = Result(course_handicap=hcp, **{f"r{i + 1}": s for i, s in enumerate(scores)})
    object_session(t).add(reg)
    return reg


def test_gross_leaderboard(session, course, member_factory):
    t = _tournament(session, course, "stroke_gross")
    a = _enter(t, member_factory(), 2, [75])
    b = _enter(t, member_factory(), 20, [90])
    c = _enter(t, member_factory(), 10, [75])
    lb.recalculate(t)
    assert (a.result.position, b.result.position, c.result.position) == (1, 3, 1)


def test_net_leaderboard_uses_course_handicap(session, course, member_factory):
    t = _tournament(session, course, "stroke_net")
    a = _enter(t, member_factory(), 2, [75])  # net 73
    b = _enter(t, member_factory(), 20, [90])  # net 70
    lb.recalculate(t)
    assert b.result.total_net == 70
    assert (b.result.position, a.result.position) == (1, 2)


def test_stableford_higher_is_better(session, course, member_factory):
    t = _tournament(session, course, "stableford")
    a = _enter(t, member_factory(), 0, [72])  # 36 points
    b = _enter(t, member_factory(), 18, [86])  # 36 + 72 + 18 - 86 = 40
    lb.recalculate(t)
    assert b.result.stableford_points == 40
    assert (b.result.position, a.result.position) == (1, 2)


def test_category_positions(session, course, member_factory):
    t = _tournament(session, course, "stroke_gross")
    m1 = _enter(t, member_factory(), 0, [72], "men")
    w1 = _enter(t, member_factory(gender="F"), 0, [80], "women")
    m2 = _enter(t, member_factory(), 0, [85], "men")
    w2 = _enter(t, member_factory(gender="F"), 0, [78], "women")
    lb.recalculate(t)
    assert [r.result.position for r in (m1, w2, w1, m2)] == [1, 2, 3, 4]
    assert (m1.result.category_position, m2.result.category_position) == (1, 2)
    assert (w2.result.category_position, w1.result.category_position) == (1, 2)
    overall, cats = lb.boards(t)
    assert [b.title for b in cats] == ["Мужчины", "Женщины"]
    assert overall.rows[0].registration is m1


def test_more_rounds_played_ranks_first_in_progress(session, course, member_factory):
    t = _tournament(session, course, "stroke_gross", rounds=2)
    a = _enter(t, member_factory(), 0, [80, 82])
    b = _enter(t, member_factory(), 0, [70])
    lb.recalculate(t)
    assert (a.result.position, b.result.position) == (1, 2)


def test_unconfirmed_and_empty_results_are_not_ranked(session, course, member_factory):
    t = _tournament(session, course, "stroke_gross")
    a = _enter(t, member_factory(), 0, [80])
    b = _enter(t, member_factory(), 0, [])
    c = _enter(t, member_factory(), 0, [70])
    c.status = "rejected"
    lb.recalculate(t)
    assert a.result.position == 1
    assert b.result.position is None
    assert c.result.position is None


def test_assign_category(member_factory, session):
    on = date(2026, 6, 1)
    junior = member_factory(birth=date(2012, 1, 1))
    senior = member_factory(birth=date(1960, 1, 1), gender="F")
    adult = member_factory(birth=date(1990, 1, 1), gender="F")
    cats = ["men", "women", "juniors", "seniors"]
    assert lb.assign_category(junior, cats, on) == "juniors"
    assert lb.assign_category(senior, cats, on) == "seniors"
    assert lb.assign_category(adult, cats, on) == "women"
    assert lb.assign_category(junior, ["men", "women"], on) == "men"
    assert lb.assign_category(adult, ["juniors"], on) == ""
