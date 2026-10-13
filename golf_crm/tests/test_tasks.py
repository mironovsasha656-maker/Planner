"""Task system: service rules and HTTP flows (director creates, manager completes, notifications)."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import seed
from app import timeutil as msk
from app.db import Base, get_session, make_engine
from app.main import app
from app.models import AuditLog, Notification, Task, User
from app.services import tasks as svc
from app.services.users import ensure_users

NOW = datetime(2026, 6, 1, 12, 0)


# ---------------------------------------------------------------- service level

@pytest.fixture
def people(session):
    ensure_users(session)
    return {u.id: u for u in session.scalars(select(User))}


def form(**kw):
    base = {"title": "Подготовить протокол", "description": "Описание задачи", "assignee_id": "2",
            "priority": "normal", "due_date": "05.06.2026", "due_time": "18:00", "related": ""}
    base.update(kw)
    return base


def make_task(session, people, due=NOW + timedelta(days=4)):
    data, errors = svc.validate(form(), session, NOW)
    assert not errors
    data["due_at"] = due
    return svc.create(session, people[1], data, NOW)


def notes(session, user_id, kind=None):
    stmt = select(Notification).where(Notification.recipient_id == user_id)
    if kind:
        stmt = stmt.where(Notification.type == kind)
    return list(session.scalars(stmt))


def test_validation_messages_are_russian(session, people):
    _, errors = svc.validate(form(title="", description="", assignee_id="1", due_date="31.02.2026",
                                  due_time="25:00", related="club:999"), session, NOW)
    assert errors == {
        "title": "Укажите название задачи.",
        "description": "Опишите, что нужно сделать.",
        "assignee_id": "Выберите исполнителя.",  # the director is not a manager
        "due_date": "Дата должна быть в формате ДД.ММ.ГГГГ.",
        "due_time": "Время в формате ЧЧ:ММ, например 18:00.",
        "related": "Выберите объект из списка.",
    }


def test_due_must_be_in_the_future(session, people):
    _, errors = svc.validate(form(due_date="01.06.2026", due_time="11:59"), session, NOW)
    assert errors == {"due_date": "Срок должен быть в будущем."}
    data, errors = svc.validate(form(), session, NOW)
    assert not errors and data["due_at"] == datetime(2026, 6, 5, 18, 0)


def test_create_notifies_assignee_and_logs(session, people):
    task = make_task(session, people)
    assert task.status == "new" and task.assignee_id == 2
    [n] = notes(session, 2, "task_assigned")
    assert "поручила вам задачу «Подготовить протокол»" in n.text and not n.is_read
    assert session.scalar(select(AuditLog).where(AuditLog.entity_type == "task", AuditLog.entity_id == task.id))


def test_only_director_creates_and_only_assignee_completes(session, people):
    data, _ = svc.validate(form(), session, NOW)
    with pytest.raises(svc.TaskError):
        svc.create(session, people[2], data, NOW)
    task = make_task(session, people)
    with pytest.raises(svc.TaskError):
        svc.complete(session, task, people[3], "", NOW)
    with pytest.raises(svc.TaskError):
        svc.cancel(session, task, people[2], NOW)


def test_start_then_complete_early_notifies_director(session, people):
    task = make_task(session, people, due=NOW + timedelta(days=2, hours=3))
    svc.start(session, task, people[2], NOW + timedelta(hours=1))
    assert task.status == "in_progress" and notes(session, 1, "task_started")
    svc.complete(session, task, people[2], "Готово", NOW + timedelta(hours=2))
    assert task.status == "done" and task.is_early and not task.overdue
    [n] = notes(session, 1, "task_completed")
    assert "Иван Петров выполнил задачу «Подготовить протокол» — досрочно, на 2 дня 1 ч раньше срока" in n.text
    assert "Комментарий: Готово" in n.text
    with pytest.raises(svc.TaskError):
        svc.complete(session, task, people[2], "", NOW)


def test_complete_directly_from_new_sets_started(session, people):
    task = make_task(session, people)
    svc.complete(session, task, people[2], "", NOW + timedelta(minutes=5))
    assert task.started_at == task.completed_at


def test_late_completion_is_not_early(session, people):
    task = make_task(session, people, due=NOW + timedelta(hours=1))
    svc.complete(session, task, people[2], "", NOW + timedelta(hours=3, minutes=30))
    assert not task.is_early
    assert svc.timing_text(task) == "с опозданием на 2 ч 30 мин"


def test_overdue_is_derived_and_notified_once(session, people):
    task = make_task(session, people, due=NOW + timedelta(hours=1))
    later = NOW + timedelta(hours=2)
    assert task.is_overdue(later) and not task.is_overdue(NOW)
    assert svc.sync_overdue(session, later) == 1
    assert svc.sync_overdue(session, later + timedelta(hours=1)) == 0
    assert len(notes(session, 2, "task_overdue")) == 1 and len(notes(session, 1, "task_overdue")) == 1
    svc.cancel(session, task, people[1], later)
    assert not task.is_overdue(later) and task.display_status == "cancelled"
    assert notes(session, 2, "task_cancelled")


def test_reassigning_notifies_both_managers(session, people):
    task = make_task(session, people)
    data, _ = svc.validate(form(assignee_id="3"), session, NOW)
    svc.update(session, task, people[1], data, NOW)
    assert task.assignee_id == 3 and task.status == "new"
    assert notes(session, 2, "task_cancelled") and notes(session, 3, "task_assigned")


def test_humanize():
    assert svc.humanize(timedelta(minutes=45)) == "45 мин"
    assert svc.humanize(timedelta(days=1, hours=3, minutes=10)) == "1 день 3 ч"
    assert svc.humanize(timedelta(days=5)) == "5 дней"


# ---------------------------------------------------------------- HTTP level

@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("tasksdb") / "test.db"
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


def client(user_id):
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("user", str(user_id))
    return c


def future(days=3):
    return (msk.today() + timedelta(days=days)).strftime("%d.%m.%Y")


def test_seeded_tasks_cover_every_state(db):
    with db() as s:
        tasks = list(s.scalars(select(Task)))
        states = {t.display_status for t in tasks}
        assert {"new", "in_progress", "done", "cancelled", "overdue"} <= states
        assert any(t.is_early for t in tasks)
        assert s.scalar(select(Notification).where(Notification.type == "task_overdue"))


def test_pages_render_for_director_and_manager(db):
    director, manager = client(1), client(2)
    for url in ("/", "/tasks", "/tasks?status=overdue", "/tasks?status=done&assignee=2", "/tasks?status=all&q=протокол",
                "/tasks/new", "/tasks/1", "/tasks/1/panel", "/notifications", "/notifications?show=unread",
                "/notifications/menu", "/tasks/related-search?rq=кубок", "/tasks/related-search?rq="):
        r = director.get(url)
        assert r.status_code == 200, url
    for url in ("/", "/tasks/my", "/tasks/my?show=done", "/tasks/my?show=all", "/tasks/1", "/notifications"):
        assert manager.get(url).status_code == 200, url
    page = director.get("/").text
    assert "+ Новая задача" not in page and "Новая задача" in page
    assert "ДЕМО: настоящая авторизация не реализована" in page
    assert "Новая задача" not in client(3).get("/players").text


def test_access_rules(db):
    manager, other = client(2), client(3)
    assert manager.get("/tasks").status_code == 403
    assert manager.get("/tasks/new").status_code == 403
    assert manager.post("/tasks/new", data={"title": "x"}).status_code == 403
    assert client(1).get("/tasks/my").status_code == 403
    with db() as s:
        foreign = s.scalar(select(Task).where(Task.assignee_id == 2, Task.status.in_(("new", "in_progress"))))
    assert other.get(f"/tasks/{foreign.id}").status_code == 403
    assert other.post(f"/tasks/{foreign.id}/complete").status_code == 403


def test_modal_form_errors_stay_in_modal(db):
    r = client(1).post("/tasks/new", data={"title": "", "description": "", "assignee_id": "", "priority": "normal",
                                           "due_date": "01.01.2020", "due_time": "10:00"},
                       headers={"HX-Request": "true"})
    assert r.status_code == 200  # htmx swaps only 2xx: the modal re-renders with inline errors
    assert 'id="modal-title"' in r.text
    for text in ("Укажите название задачи.", "Опишите, что нужно сделать.", "Выберите исполнителя.",
                 "Срок должен быть в будущем."):
        assert text in r.text


def test_create_via_modal_then_manager_completes_early(db):
    director, manager = client(1), client(4)
    r = director.post("/tasks/new", headers={"HX-Request": "true"}, data={
        "title": "Обновить сайт клуба", "description": "Проверить контакты", "assignee_id": "4",
        "priority": "high", "due_date": future(), "due_time": "18:00", "related": "club:1"})
    assert r.status_code == 200 and r.text == ""
    events = json.loads(r.headers["HX-Trigger"])
    assert events["closeModal"] and events["tasksChanged"] and events["toast"]["text"] == "Задача создана"
    with db() as s:
        task = s.scalar(select(Task).where(Task.title == "Обновить сайт клуба"))
        tid = task.id
        assert task.related_type == "club" and task.priority == "high"
        assert s.scalar(select(Notification).where(Notification.task_id == tid, Notification.recipient_id == 4))
        before = s.scalar(select(Notification.id).where(Notification.recipient_id == 1)
                          .order_by(Notification.id.desc()).limit(1))
    assert "Обновить сайт клуба" in manager.get("/tasks/my").text
    r = manager.post(f"/tasks/{tid}/complete", headers={"HX-Request": "true"}, data={"comment": "Сделано"})
    assert r.status_code == 200 and "Выполнена досрочно" in r.text
    assert "досрочно" in json.loads(r.headers["HX-Trigger"])["toast"]["text"]
    poll = director.get(f"/notifications/poll?since={before}")
    payload = json.loads(poll.headers["HX-Trigger"])["newNotifications"]
    assert any("Алексей Волков выполнил задачу «Обновить сайт клуба» — досрочно" in n["text"] for n in payload["items"])
    assert 'class="dot"' in poll.text
    first = director.get("/notifications/poll?since=-1")
    assert json.loads(first.headers["HX-Trigger"])["newNotifications"]["items"] == []
    with db() as s:
        assert s.scalar(select(AuditLog).where(AuditLog.entity_type == "task", AuditLog.entity_id == tid,
                                               AuditLog.user == "Менеджер: Алексей Волков"))


def test_start_and_cancel_without_htmx(db):
    director, manager = client(1), client(2)
    with db() as s:
        tid = s.scalar(select(Task.id).where(Task.assignee_id == 2, Task.status == "new"))
    r = manager.post(f"/tasks/{tid}/start")
    assert r.status_code == 303
    r = manager.post(f"/tasks/{tid}/start")  # second start is refused with a message
    assert r.status_code == 303 and "flash" in r.headers["set-cookie"]
    r = director.post(f"/tasks/{tid}/cancel")
    assert r.status_code == 303
    with db() as s:
        t = s.get(Task, tid)
        assert t.status == "cancelled" and t.started_at is not None
    assert director.get(f"/tasks/{tid}/edit").status_code == 303


def test_edit_task(db):
    director = client(1)
    with db() as s:
        t = s.scalar(select(Task).where(Task.status == "new", Task.due_at > msk.now()))
        tid = t.id
    assert director.get(f"/tasks/{tid}/edit", headers={"HX-Request": "true"}).status_code == 200
    r = director.post(f"/tasks/{tid}/edit", headers={"HX-Request": "true"}, data={
        "title": "Изменённое название", "description": "Новое описание", "assignee_id": "3", "priority": "low",
        "due_date": future(10), "due_time": "09:30"})
    assert r.status_code == 200 and json.loads(r.headers["HX-Trigger"])["closeModal"]
    with db() as s:
        t = s.get(Task, tid)
        assert (t.title, t.assignee_id, t.priority, t.due_at.strftime("%H:%M")) == ("Изменённое название", 3, "low", "09:30")


def test_notifications_read(db):
    manager = client(3)
    with db() as s:
        n = s.scalar(select(Notification).where(Notification.recipient_id == 3, Notification.is_read.is_(False)))
        nid = n.id
    r = manager.get(f"/notifications/{nid}/open")
    assert r.status_code == 303 and r.headers["location"].startswith("/tasks/")
    assert client(2).get(f"/notifications/{nid}/open").status_code == 404
    manager.post("/notifications/read-all")
    with db() as s:
        assert not s.scalar(select(Notification).where(Notification.recipient_id == 3,
                                                       Notification.is_read.is_(False)))


def test_user_switch(db):
    r = TestClient(app, follow_redirects=False).post("/user", data={"user": "3"},
                                                     headers={"referer": "http://testserver/tournaments"})
    assert r.status_code == 303 and r.headers["location"] == "/"  # manager Мария has no tournaments access
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("user=3") for c in cookies) and any(c.startswith("role=accountant") for c in cookies)
    page = client(3).get("/tasks/my").text
    assert 'value="3" selected' in page
