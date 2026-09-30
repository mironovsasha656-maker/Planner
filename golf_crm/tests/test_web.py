"""End-to-end checks through the HTTP layer on a freshly seeded temporary database."""
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import seed
from app.db import Base, get_session, make_engine
from app.main import app
from app.models import AuditLog, Member, Message, Payment, Registration, Tournament
from app import timeutil as msk


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    engine = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        seed.seed(s, msk.today())

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield factory
    app.dependency_overrides.clear()


def client(role="admin"):
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("role", role)
    return c


PAGES = [
    "/", "/players", "/players?status=unpaid&age=senior&sort=-hcp", "/players?q=MO-2026&hcp_min=10&hcp_max=20",
    "/players/1", "/players/1?tab=handicap", "/players/1?tab=tournaments", "/players/1?tab=payments",
    "/players/new", "/players/1/edit", "/clubs", "/clubs/1", "/tournaments", "/tournaments?view=calendar",
    "/tournaments?view=calendar&month=2026-05", "/tournaments/new", "/handicap", "/handicap?stale=1",
    "/finance", "/finance?tab=debtors", "/finance?tab=summary", "/finance?status=overdue&type=membership",
    "/finance/payments/new", "/officials", "/officials?role=referee", "/officials/new", "/officials/1/edit",
    "/mailings", "/mailings/new", "/mailings/new?segment=debtors", "/mailings/1",
    "/mailings/preview?segment=club&club_id=1", "/audit", "/audit?action=payment", "/search?q=кубок",
    "/search/quick?q=ив",
]


def test_all_pages_render_for_admin(db):
    c = client()
    with db() as s:
        tids = [t.id for t in s.scalars(select(Tournament))]
    pages = PAGES + [f"/tournaments/{t}?tab={tab}" for t in tids
                     for tab in ("overview", "registrations", "results", "leaderboard")]
    pages += [f"/tournaments/{t}/print/{kind}" for t in tids for kind in ("start", "final")]
    for url in pages:
        r = c.get(url)
        assert r.status_code == 200, url
        assert "Traceback" not in r.text
        assert "Lorem" not in r.text


def test_role_restrictions(db):
    sec, acc = client("secretary"), client("accountant")
    assert sec.get("/tournaments").status_code == 200
    assert sec.get("/finance").status_code == 403
    assert sec.get("/audit").status_code == 403
    assert acc.get("/finance").status_code == 200
    assert acc.get("/players").status_code == 200
    assert acc.get("/players/new").status_code == 403
    assert acc.post("/players/1/status", data={"status": "active"}).status_code == 403
    assert acc.get("/tournaments").status_code == 403
    page = acc.get("/players/1").text
    assert "Редактировать" not in page
    assert "ДЕМО: настоящая авторизация не реализована" in page
    # accountant navigation shows only allowed sections
    nav = re.search(r'<nav class="nav">(.*?)</nav>', page, re.S).group(1)
    assert "Финансы" in nav and "Турниры" not in nav


def test_role_switch_sets_cookie(db):
    c = client()
    r = c.post("/role", data={"role": "accountant"}, headers={"referer": "http://testserver/tournaments"})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "role=accountant" in r.headers["set-cookie"]


def test_csv_export_is_excel_friendly(db):
    r = client().get("/players/export.csv?status=unpaid")
    assert r.status_code == 200
    assert r.content.startswith("﻿".encode("utf-8"))
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Лицензия;ФИО;")
    assert len(lines) > 1 and all("Не оплачен взнос" in line for line in lines[1:])
    fin = client("accountant").get("/finance/export.csv?type=membership")
    assert fin.status_code == 200 and fin.content.startswith(b"\xef\xbb\xbf")


def test_player_validation_messages(db):
    r = client().post("/players/new", data={"last_name": "", "first_name": "Иван", "birth_date": "2030-01-01",
                                            "gender": "M", "status": "active", "join_date": "2020-01-01",
                                            "email": "не-почта", "handicap_index": "60"})
    assert r.status_code == 400
    for text in ("Укажите фамилию.", "Игроку должно быть не меньше 5 лет.",
                 "Введите корректный адрес электронной почты.", "Индекс гандикапа должен быть от 0,0 до 54,0."):
        assert text in r.text


def test_create_player_issues_membership_invoice(db):
    c = client("secretary")
    r = c.post("/players/new", data={"last_name": "Тестов", "first_name": "Пётр", "middle_name": "Ильич",
                                     "birth_date": "1990-04-12", "gender": "M", "status": "active",
                                     "join_date": msk.today().isoformat(), "handicap_index": "24,3",
                                     "email": "petr.testov@example.com", "pd_consent": "on"})
    assert r.status_code == 303
    mid = int(r.headers["location"].rsplit("/", 1)[1])
    with db() as s:
        m = s.get(Member, mid)
        assert m.handicap_index == 24.3
        assert re.fullmatch(r"MO-\d{4}-\d{4}", m.license_number)
        assert [p.amount for p in m.payments] == [5000]
        assert s.scalar(select(AuditLog).where(AuditLog.entity_id == mid, AuditLog.action == "create"))


def test_registration_limit_and_waitlist_via_http(db):
    c = client("secretary")
    with db() as s:
        t = s.scalar(select(Tournament).where(Tournament.name == "Кубок «Серебряных Ключей»"))
        assert t.is_full and t.waitlist_count == 4
        registered = {r.member_id for r in t.registrations}
        newcomer = s.scalar(select(Member).where(Member.id.not_in(registered), Member.status == "active"))
        tid, nid = t.id, newcomer.id
        occupied_reg = next(r for r in t.registrations if r.status == "applied")
        first_wait = sorted((r for r in t.registrations if r.status == "waitlist"), key=lambda r: (r.applied_on, r.id))[0]
        occ_id, wait_id = occupied_reg.id, first_wait.id
    r = c.post(f"/tournaments/{tid}/register", data={"member_id": str(nid)})
    assert r.status_code == 303
    with db() as s:
        reg = s.scalar(select(Registration).where(Registration.tournament_id == tid, Registration.member_id == nid))
        assert reg.status == "waitlist"
    # confirming a waitlisted player while full is refused
    r = c.post(f"/registrations/{wait_id}/status", data={"status": "confirmed"})
    assert "flash" in r.headers.get("set-cookie", "")
    with db() as s:
        assert s.get(Registration, wait_id).status == "waitlist"
    # rejecting an occupying registration promotes the first waitlisted one
    c.post(f"/registrations/{occ_id}/status", data={"status": "rejected"})
    with db() as s:
        assert s.get(Registration, occ_id).status == "rejected"
        assert s.get(Registration, wait_id).status == "applied"
        assert s.get(Tournament, tid).occupied == s.get(Tournament, tid).max_participants


def test_results_entry_and_finish_updates_handicap(db):
    c = client("secretary")
    with db() as s:
        t = s.scalar(select(Tournament).where(Tournament.status == "in_progress"))
        tid = t.id
        regs = [r for r in t.registrations if r.status == "confirmed"]
        form = {}
        for r in regs:
            for k in range(1, t.rounds_count + 1):
                form[f"r{k}_{r.id}"] = str(getattr(r.result, f"r{k}") or 90)
        member_id = regs[0].member_id
        rounds_before = len(s.get(Member, member_id).rounds)
    bad = dict(form, **{next(iter(form)): "17"})
    r = c.post(f"/tournaments/{tid}/results", data=bad)
    assert r.status_code == 400 and "Целое число 55–200" in r.text
    r = c.post(f"/tournaments/{tid}/results", data=form)
    assert r.status_code == 303
    with db() as s:
        t = s.get(Tournament, tid)
        positions = sorted(r.result.position for r in t.registrations if r.status == "confirmed")
        assert positions[0] == 1
        assert all(r.result.rounds_played == t.rounds_count for r in t.registrations if r.status == "confirmed")
    r = c.post(f"/tournaments/{tid}/status", data={"status": "finished"})
    assert r.status_code == 303
    with db() as s:
        assert s.get(Tournament, tid).status == "finished"
        assert len(s.get(Member, member_id).rounds) == rounds_before + 3
    assert c.get(f"/tournaments/{tid}/print/final").status_code == 200


def test_mark_paid_restores_member_status(db):
    acc = client("accountant")
    with db() as s:
        p = s.scalar(select(Payment).where(Payment.status == "overdue", Payment.type == "membership"))
        pid, mid = p.id, p.member_id
        assert p.member.status == "unpaid"
    r = acc.post(f"/finance/payments/{pid}/paid")
    assert r.status_code == 303
    with db() as s:
        assert s.get(Payment, pid).status == "paid"
        assert s.get(Payment, pid).paid_on == msk.today()
        assert s.get(Member, mid).status == "active"


def test_add_round_and_recalculate(db):
    c = client("secretary")
    with db() as s:
        m = s.get(Member, 5)
        tee_id = m.rounds[0].tee.id
        count = len(m.rounds)
    r = c.post("/players/5/rounds", data={"played_on": msk.today().isoformat(), "tee_id": str(tee_id), "score": "15"})
    with db() as s:
        assert len(s.get(Member, 5).rounds) == count
    c.post("/players/5/rounds", data={"played_on": msk.today().isoformat(), "tee_id": str(tee_id), "score": "72"})
    r = c.post("/players/5/recalc")
    assert r.status_code == 303
    with db() as s:
        assert len(s.get(Member, 5).rounds) == count + 1
    assert client().post("/handicap/recalc-all").status_code == 303


def test_mailing_is_simulated_and_logged(db):
    c = client()
    r = c.post("/mailings/new", data={"segment": "club", "club_id": "1", "subject": "", "body": ""})
    assert r.status_code == 400 and "Укажите тему письма." in r.text
    r = c.post("/mailings/new", data={"segment": "juniors", "subject": "Сбор", "body": "Текст"})
    assert r.status_code == 303
    with db() as s:
        msg = s.scalar(select(Message).order_by(Message.id.desc()))
        assert msg.subject == "Сбор" and msg.recipients_count > 0
        assert s.scalar(select(AuditLog).where(AuditLog.action == "mailing", AuditLog.entity_id == msg.id))


def test_body_size_limit(db):
    r = client().post("/players/new", data={"notes": "x" * 70_000})
    assert r.status_code == 413


def test_create_tournament_and_open_registration(db):
    c = client("secretary")
    bad = c.post("/tournaments/new", data={"name": "", "start_date": "10.11.2026", "end_date": "09.11.2026",
                                           "registration_deadline": "12.11.2026", "course_id": "1",
                                           "format": "stroke_net", "rounds_count": "3", "entry_fee": "3000",
                                           "max_participants": "1", "status": "draft"})
    assert bad.status_code == 400
    for text in ("Укажите название турнира.", "Окончание не может быть раньше начала.",
                 "Срок подачи заявок должен быть не позже даты начала.", "Лимит — от 2 до 200 участников."):
        assert text in bad.text
    r = c.post("/tournaments/new", data={"name": "Кубок проверки", "start_date": "10.11.2026",
                                         "end_date": "11.11.2026", "registration_deadline": "05.11.2026",
                                         "course_id": "1", "format": "stableford", "categories": ["men", "women"],
                                         "rounds_count": "2", "entry_fee": "2000", "max_participants": "40",
                                         "status": "draft"})
    assert r.status_code == 303
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    c.post(f"/tournaments/{tid}/status", data={"status": "registration"})
    with db() as s:
        t = s.get(Tournament, tid)
        assert t.status == "registration" and t.start_date == date(2026, 11, 10) and t.category_codes == ["men", "women"]
    # finishing directly from registration is not an allowed transition
    c.post(f"/tournaments/{tid}/status", data={"status": "finished"})
    with db() as s:
        assert s.get(Tournament, tid).status == "registration"


def test_raising_limit_promotes_waitlist(db):
    c = client("secretary")
    with db() as s:
        t = s.scalar(select(Tournament).where(Tournament.name == "Кубок «Серебряных Ключей»"))
        tid, waiting = t.id, t.waitlist_count
        form = {"name": t.name, "start_date": t.start_date.strftime("%d.%m.%Y"),
                "end_date": t.end_date.strftime("%d.%m.%Y"),
                "registration_deadline": t.registration_deadline.strftime("%d.%m.%Y"),
                "course_id": str(t.course_id), "format": t.format, "categories": t.category_codes,
                "rounds_count": str(t.rounds_count), "entry_fee": str(t.entry_fee),
                "max_participants": str(t.max_participants + 2), "description": t.description}
    assert waiting >= 2
    r = c.post(f"/tournaments/{tid}/edit", data=form)
    assert r.status_code == 303
    with db() as s:
        t = s.get(Tournament, tid)
        assert t.waitlist_count == waiting - 2 and t.is_full


def test_user_input_is_escaped(db):
    c = client()
    r = c.post("/players/new", data={"last_name": "<script>alert(1)</script>", "first_name": "Хакер",
                                     "birth_date": "01.01.1990", "gender": "M", "status": "active",
                                     "join_date": "01.01.2020", "notes": "<b>жирный</b>"})
    assert r.status_code == 303
    page = c.get(r.headers["location"]).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
