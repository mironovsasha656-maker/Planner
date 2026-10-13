import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, make_engine  # noqa: E402
from app.models import Club, Course, CourseTee, Member  # noqa: E402


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture
def course(session):
    club = Club(name="Тестовый клуб", district="Тестовый г. о.", address="—", contact_person="—",
                phone="—", holes=18)
    c = Course(name="Тестовое поле", holes=18)
    c.tees = [
        CourseTee(color="yellow", course_rating=72.0, slope_rating=113, par=72),
        CourseTee(color="red", course_rating=72.0, slope_rating=113, par=72),
    ]
    club.courses.append(c)
    session.add(club)
    session.flush()
    return c


_counter = iter(range(1, 10_000))


def make_member(session, club=None, gender="M", birth=date(1985, 5, 1), index=20.0, consent=True,
                email="player@example.com", status="active"):
    n = next(_counter)
    m = Member(last_name=f"Игроков{n}", first_name="Иван", middle_name="Иванович", birth_date=birth,
               gender=gender, email=email, club=club, status=status, join_date=date(2020, 1, 1),
               handicap_index=index, license_number=f"MO-2026-{n:04d}", pd_consent=consent)
    session.add(m)
    session.flush()
    return m


@pytest.fixture
def member_factory(session):
    def factory(**kw):
        return make_member(session, **kw)

    return factory
