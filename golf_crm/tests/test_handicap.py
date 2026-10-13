from datetime import date, timedelta

import pytest

from app.services import handicap as h


def test_differential_basic():
    # (113 / 113) * (90 - 72.0) = 18.0
    assert h.score_differential(90, 72.0, 113) == 18.0


def test_differential_slope_scaling():
    # (113 / 130) * (95 - 71.5) = 20.426... -> 20.4
    assert h.score_differential(95, 71.5, 130) == 20.4


def test_differential_below_rating_is_negative():
    assert h.score_differential(70, 72.4, 125) == pytest.approx(-2.2)


def test_differential_rounds_half_up():
    # (113/113) * (80 - 71.95) = 8.05 -> 8.1 (banker's rounding would give 8.0)
    assert h.score_differential(80, 71.95, 113) == 8.1


def test_differential_rejects_bad_slope():
    with pytest.raises(ValueError):
        h.score_differential(80, 72.0, 0)


def test_index_needs_three_rounds():
    assert h.handicap_index([]) is None
    assert h.handicap_index([10.0, 12.0]) is None


@pytest.mark.parametrize(
    "diffs, expected",
    [
        ([10.0, 12.0, 14.0], 8.0),  # 3 -> lowest - 2.0
        ([10.0, 12.0, 14.0, 16.0], 9.0),  # 4 -> lowest - 1.0
        ([15.0, 10.0, 12.0, 14.0, 16.0], 10.0),  # 5 -> lowest
        ([10.0, 11.0, 14.0, 15.0, 16.0, 17.0], 9.5),  # 6 -> avg(lowest 2) - 1.0
        ([10.0, 11.0, 14.0, 15.0, 16.0, 17.0, 18.0], 10.5),  # 7 -> avg(lowest 2)
        ([10.0, 11.0, 12.0] + [20.0] * 6, 11.0),  # 9 -> avg(lowest 3)
        ([10.0, 11.0, 12.0, 13.0] + [20.0] * 8, 11.5),  # 12 -> avg(lowest 4)
        ([10.0, 11.0, 12.0, 13.0, 14.0] + [20.0] * 10, 12.0),  # 15 -> avg(lowest 5)
        ([10.0, 11.0, 12.0, 13.0, 14.0, 15.0] + [20.0] * 11, 12.5),  # 17 -> avg(lowest 6)
        ([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0] + [20.0] * 12, 13.0),  # 19 -> avg(lowest 7)
    ],
)
def test_index_small_sample_table(diffs, expected):
    assert h.handicap_index(diffs) == expected


def test_index_best_8_of_20():
    diffs = [float(x) for x in range(1, 21)]  # 1..20 -> best 8 = 1..8, avg 4.5
    assert h.handicap_index(diffs) == 4.5


def test_index_uses_only_most_recent_20():
    old_great_rounds = [0.0] * 5
    recent = [float(x) for x in range(11, 31)]  # 11..30 -> best 8 = 11..18, avg 14.5
    assert h.handicap_index(old_great_rounds + recent) == 14.5


def test_index_is_clamped():
    assert h.handicap_index([-5.0, -4.0, -3.0]) == 0.0
    assert h.handicap_index([70.0, 71.0, 72.0, 73.0, 74.0]) == 54.0


def test_counted_positions_marks_best_differentials():
    diffs = [15.0, 10.0, 12.0, 14.0, 16.0]
    assert h.counted_positions(diffs) == {1}
    assert h.counted_positions([1.0, 2.0]) == set()


def test_course_handicap():
    # 18.4 * 130 / 113 + (72.5 - 72) = 21.67 -> 22
    assert h.course_handicap(18.4, 130, 72.5, 72) == 22
    assert h.course_handicap(0.0, 113, 70.0, 72) == -2


def test_index_history_is_chronological():
    start = date(2026, 5, 1)
    rounds = [(start + timedelta(days=i), d) for i, d in enumerate([20.0, 18.0, 16.0, 14.0])]
    history = h.index_history(reversed(rounds))
    assert [p.index for p in history] == [None, None, 14.0, 13.0]
    assert history[0].played_on == start
