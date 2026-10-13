"""Task system: the director assigns tasks to managers; managers start and complete them.

Every action writes a notification for the other side and an audit log entry.
"Overdue" is derived (open task with due_at in the past) and never stored.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from app.labels import RELATED_TYPE, TASK_PRIORITY
from app.models import Club, Member, Notification, Task, Tournament, User
from app.services import audit
from app.services import formatting as f
from app.services.users import verb

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
RELATED_MODELS = {"tournament": Tournament, "member": Member, "club": Club}
RELATED_URLS = {"tournament": "/tournaments/{}", "member": "/players/{}", "club": "/clubs/{}"}


class TaskError(ValueError):
    """Business rule violation; the message is shown to the user (Russian)."""


# ---------------------------------------------------------------- formatting helpers

def fmt_dt(value: Optional[datetime]) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "—"


def humanize(delta: timedelta) -> str:
    """Russian duration: "2 дня 3 ч", "45 мин"."""
    minutes = max(0, int(delta.total_seconds() // 60))
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} {f.plural(days, 'день', 'дня', 'дней')}")
    if hours:
        parts.append(f"{hours} ч")
    if not days and (mins or not parts):
        parts.append(f"{mins} мин")
    return " ".join(parts[:2])


def timing_text(task: Task) -> str:
    """How a completed task relates to its deadline."""
    if task.completed_at is None:
        return ""
    if task.completed_at < task.due_at:
        return f"досрочно, на {humanize(task.due_at - task.completed_at)} раньше срока"
    if task.completed_at == task.due_at:
        return "точно в срок"
    return f"с опозданием на {humanize(task.completed_at - task.due_at)}"


def related_of(session: Session, task: Task) -> Optional[dict]:
    if not task.related_type or not task.related_id:
        return None
    model = RELATED_MODELS.get(task.related_type)
    obj = session.get(model, task.related_id) if model else None
    if obj is None:
        return None
    name = obj.full_name if task.related_type == "member" else obj.name
    return {"type": RELATED_TYPE[task.related_type], "name": name,
            "url": RELATED_URLS[task.related_type].format(obj.id), "value": f"{task.related_type}:{obj.id}"}


# ---------------------------------------------------------------- validation

def validate(form, session: Session, now: datetime) -> tuple[dict, dict]:
    """Validate the task form. Returns (clean values, errors) — errors are Russian messages."""
    raw = {k: (form.get(k) or "").strip() for k in
           ("title", "description", "assignee_id", "priority", "due_date", "due_time", "related")}
    errors: dict[str, str] = {}
    if not raw["title"]:
        errors["title"] = "Укажите название задачи."
    elif len(raw["title"]) > 200:
        errors["title"] = "Название — не более 200 символов."
    if not raw["description"]:
        errors["description"] = "Опишите, что нужно сделать."
    elif len(raw["description"]) > 5000:
        errors["description"] = "Описание — не более 5000 символов."
    assignee = session.get(User, int(raw["assignee_id"])) if raw["assignee_id"].isdigit() else None
    if assignee is None or assignee.kind != "manager":
        errors["assignee_id"] = "Выберите исполнителя."
    if raw["priority"] not in TASK_PRIORITY:
        errors["priority"] = "Выберите приоритет."
    due_date = f.parse_date(raw["due_date"]) if raw["due_date"] else None
    time_match = TIME_RE.match(raw["due_time"])
    due_at = None
    if not raw["due_date"]:
        errors["due_date"] = "Укажите дату срока."
    elif due_date is None:
        errors["due_date"] = "Дата должна быть в формате ДД.ММ.ГГГГ."
    if not raw["due_time"]:
        errors["due_time"] = "Укажите время."
    elif time_match is None:
        errors["due_time"] = "Время в формате ЧЧ:ММ, например 18:00."
    if due_date and time_match:
        due_at = datetime(due_date.year, due_date.month, due_date.day,
                          int(time_match.group(1)), int(time_match.group(2)))
        if due_at <= now:
            errors["due_date"] = "Срок должен быть в будущем."
        elif due_at > now + timedelta(days=366):
            errors["due_date"] = "Срок — не дальше чем через год."
    related_type, related_id = None, None
    if raw["related"]:
        kind, _, ident = raw["related"].partition(":")
        model = RELATED_MODELS.get(kind)
        if model is None or not ident.isdigit() or session.get(model, int(ident)) is None:
            errors["related"] = "Выберите объект из списка."
        else:
            related_type, related_id = kind, int(ident)
    clean = dict(title=raw["title"], description=raw["description"], assignee=assignee,
                 priority=raw["priority"], due_at=due_at, related_type=related_type, related_id=related_id)
    return clean, errors


# ---------------------------------------------------------------- notifications

def notify(session: Session, recipient: User, kind: str, task: Task, text: str, now: datetime) -> Notification:
    n = Notification(recipient_id=recipient.id, type=kind, task_id=task.id, text=text[:500], created_at=now,
                     is_read=False)
    session.add(n)
    return n


def sync_overdue(session: Session, now: datetime) -> int:
    """Create one "task_overdue" notification per recipient for newly overdue tasks."""
    already = exists().where(and_(Notification.task_id == Task.id, Notification.type == "task_overdue"))
    overdue = list(session.scalars(
        select(Task).where(Task.status.in_(("new", "in_progress")), Task.due_at < now, ~already)
    ))
    for task in overdue:
        late = humanize(now - task.due_at)
        notify(session, task.assignee, "task_overdue", task,
               f"Просрочена задача «{task.title}»: срок истёк {fmt_dt(task.due_at)} ({late} назад).", now)
        notify(session, task.creator, "task_overdue", task,
               f"{task.assignee.name} не {verb(task.assignee, 'выполнил')} задачу «{task.title}» в срок ({fmt_dt(task.due_at)}).", now)
    return len(overdue)


# ---------------------------------------------------------------- actions

def create(session: Session, creator: User, data: dict, now: datetime) -> Task:
    if not creator.is_director:
        raise TaskError("Создавать задачи может только директор.")
    task = Task(title=data["title"], description=data["description"], creator_id=creator.id, creator=creator,
                assignee_id=data["assignee"].id, assignee=data["assignee"], priority=data["priority"],
                status="new", created_at=now, due_at=data["due_at"], related_type=data["related_type"],
                related_id=data["related_id"])
    session.add(task)
    session.flush()
    notify(session, task.assignee, "task_assigned", task,
           f"{creator.name} {verb(creator, 'поручил')} вам задачу «{task.title}». Срок: {fmt_dt(task.due_at)}.", now)
    audit.log(session, creator.label, "task", "task", task.id,
              f"Создана задача «{task.title}» для {task.assignee.name}, срок {fmt_dt(task.due_at)}, "
              f"приоритет «{TASK_PRIORITY[task.priority]}»", when=now)
    return task


def update(session: Session, task: Task, actor: User, data: dict, now: datetime) -> Task:
    if not actor.is_director:
        raise TaskError("Изменять задачи может только директор.")
    if not task.is_open:
        raise TaskError("Выполненную или отменённую задачу изменить нельзя.")
    old_assignee = task.assignee
    task.title, task.description, task.priority = data["title"], data["description"], data["priority"]
    task.due_at, task.related_type, task.related_id = data["due_at"], data["related_type"], data["related_id"]
    if data["assignee"].id != old_assignee.id:
        task.assignee_id, task.assignee = data["assignee"].id, data["assignee"]
        task.status, task.started_at = "new", None
        notify(session, old_assignee, "task_cancelled", task,
               f"Задача «{task.title}» передана другому исполнителю.", now)
        notify(session, task.assignee, "task_assigned", task,
               f"{actor.name} {verb(actor, 'поручил')} вам задачу «{task.title}». Срок: {fmt_dt(task.due_at)}.", now)
    else:
        notify(session, task.assignee, "task_assigned", task,
               f"{actor.name} {verb(actor, 'изменил')} задачу «{task.title}». Срок: {fmt_dt(task.due_at)}.", now)
    audit.log(session, actor.label, "task", "task", task.id,
              f"Изменена задача «{task.title}» (исполнитель {task.assignee.name}, срок {fmt_dt(task.due_at)})", when=now)
    return task


def _require_assignee(task: Task, actor: User) -> None:
    if actor.id != task.assignee_id:
        raise TaskError("Отмечать задачу может только её исполнитель.")


def start(session: Session, task: Task, actor: User, now: datetime) -> Task:
    _require_assignee(task, actor)
    if task.status != "new":
        raise TaskError("Взять в работу можно только новую задачу.")
    task.status, task.started_at = "in_progress", now
    notify(session, task.creator, "task_started", task, f"{actor.name} {verb(actor, 'взял')} в работу задачу «{task.title}».", now)
    audit.log(session, actor.label, "task", "task", task.id, f"Задача «{task.title}» взята в работу", when=now)
    return task


def complete(session: Session, task: Task, actor: User, comment: str, now: datetime) -> Task:
    _require_assignee(task, actor)
    if not task.is_open:
        raise TaskError("Задача уже выполнена или отменена.")
    comment = (comment or "").strip()
    if len(comment) > 2000:
        raise TaskError("Комментарий — не более 2000 символов.")
    if task.started_at is None:
        task.started_at = now
    task.status, task.completed_at, task.completion_comment = "done", now, comment
    timing = timing_text(task)
    text = f"{actor.name} {verb(actor, 'выполнил')} задачу «{task.title}» — {timing}."
    if comment:
        text += f" Комментарий: {comment}"
    notify(session, task.creator, "task_completed", task, text, now)
    audit.log(session, actor.label, "task", "task", task.id, f"Задача «{task.title}» выполнена ({timing})", when=now)
    return task


def cancel(session: Session, task: Task, actor: User, now: datetime) -> Task:
    if not actor.is_director:
        raise TaskError("Отменять задачи может только директор.")
    if not task.is_open:
        raise TaskError("Задача уже выполнена или отменена.")
    task.status, task.cancelled_at = "cancelled", now
    notify(session, task.assignee, "task_cancelled", task, f"{actor.name} {verb(actor, 'отменил')} задачу «{task.title}».", now)
    audit.log(session, actor.label, "task", "task", task.id, f"Задача «{task.title}» отменена", when=now)
    return task


def unread_count(session: Session, user: User) -> int:
    from sqlalchemy import func

    return session.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_id == user.id, Notification.is_read.is_(False))) or 0
