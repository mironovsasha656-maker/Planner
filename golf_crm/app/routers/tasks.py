"""Tasks: the director assigns, managers start and complete (also early), everyone gets notified.

HTMX requests get fragments (modal form, slide-over panel) plus HX-Trigger events
(tasksChanged / toast / closeModal); plain requests fall back to full pages and redirects.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import timeutil as msk
from app.db import get_session
from app.labels import TASK_PRIORITY
from app.models import Club, Member, Task, Tournament, User
from app.services import formatting as f
from app.services import tasks as svc
from app.services.users import ensure_users, managers
from app.web import back_url, current_user_id, redirect, render, require

router = APIRouter(prefix="/tasks")

PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def triggers(response: Response, **events) -> Response:
    # ensure_ascii keeps the header latin-1 safe; htmx decodes the \\u escapes.
    response.headers["HX-Trigger"] = json.dumps(events, ensure_ascii=True)
    return response


def actor(request: Request, s: Session) -> User:
    user = s.get(User, current_user_id(request))
    if user is None:
        ensure_users(s)
        s.commit()
        user = s.get(User, current_user_id(request))
    return user


def get_task(s: Session, tid: int, user: User) -> Task:
    task = s.get(Task, tid)
    if task is None:
        raise HTTPException(404)
    if not user.is_director and task.assignee_id != user.id:
        raise HTTPException(403)
    return task


def sort_key(task: Task):
    return (task.due_at, PRIORITY_ORDER[task.priority])


def enrich(s: Session, tasks: list[Task]) -> list[dict]:
    now = msk.now()
    return [{"t": t, "overdue": t.is_overdue(now), "related": svc.related_of(s, t),
             "left": svc.humanize(t.due_at - now) if t.due_at > now else svc.humanize(now - t.due_at),
             "timing": svc.timing_text(t)} for t in tasks]


# ---------------------------------------------------------------- director: all tasks

@router.get("")
def tasks_page(request: Request, s: Session = Depends(get_session), _=Depends(require("tasks"))):
    now = msk.now()
    q = request.query_params
    params = {"q": (q.get("q") or "").strip()[:100], "assignee": q.get("assignee", ""),
              "status": q.get("status", "open"), "priority": q.get("priority", "")}
    stmt = select(Task)
    if params["q"]:
        needle = params["q"].lower().replace("ё", "е")
        stmt = stmt.where(or_(func.py_lower(Task.title).contains(needle),
                              func.py_lower(Task.description).contains(needle)))
    if params["assignee"].isdigit():
        stmt = stmt.where(Task.assignee_id == int(params["assignee"]))
    if params["priority"] in TASK_PRIORITY:
        stmt = stmt.where(Task.priority == params["priority"])
    status = params["status"]
    if status == "open":
        stmt = stmt.where(Task.status.in_(("new", "in_progress")))
    elif status == "overdue":
        stmt = stmt.where(Task.status.in_(("new", "in_progress")), Task.due_at < now)
    elif status in ("new", "in_progress"):
        stmt = stmt.where(Task.status == status, Task.due_at >= now)
    elif status in ("done", "cancelled"):
        stmt = stmt.where(Task.status == status)
    tasks = list(s.scalars(stmt))
    if status in ("done", "cancelled"):
        tasks.sort(key=lambda t: t.completed_at or t.cancelled_at or t.created_at, reverse=True)
    else:
        tasks.sort(key=lambda t: (not t.is_overdue(now), sort_key(t)))

    all_tasks = list(s.scalars(select(Task)))
    week_ago = now - timedelta(days=7)
    done_week = [t for t in all_tasks if t.status == "done" and t.completed_at and t.completed_at >= week_ago]
    stats = {
        "open": sum(1 for t in all_tasks if t.is_open),
        "overdue": sum(1 for t in all_tasks if t.is_overdue(now)),
        "done_week": len(done_week),
        "early_week": sum(1 for t in done_week if t.is_early),
    }
    team = []
    for m in managers(s):
        mine = [t for t in all_tasks if t.assignee_id == m.id]
        team.append({"user": m, "open": sum(1 for t in mine if t.is_open),
                     "overdue": sum(1 for t in mine if t.is_overdue(now)),
                     "done": sum(1 for t in mine if t.status == "done")})
    return render(request, "tasks/index.html", active="tasks", title="Задачи", rows=enrich(s, tasks),
                  params=params, stats=stats, team=team, managers=managers(s))


# ---------------------------------------------------------------- manager: my tasks

@router.get("/my")
def my_tasks(request: Request, s: Session = Depends(get_session), _=Depends(require("my_tasks"))):
    user = actor(request, s)
    now = msk.now()
    show = request.query_params.get("show", "active")
    if show not in ("active", "done", "all"):
        show = "active"
    tasks = list(s.scalars(select(Task).where(Task.assignee_id == user.id)))
    groups = []
    if show in ("active", "all"):
        overdue = sorted((t for t in tasks if t.is_overdue(now)), key=lambda t: t.due_at)
        in_work = sorted((t for t in tasks if t.status == "in_progress" and not t.is_overdue(now)), key=sort_key)
        new = sorted((t for t in tasks if t.status == "new" and not t.is_overdue(now)), key=sort_key)
        groups += [("Просроченные", "overdue", overdue), ("В работе", "in_progress", in_work), ("Новые", "new", new)]
    if show in ("done", "all"):
        done = sorted((t for t in tasks if t.status in ("done", "cancelled")),
                      key=lambda t: t.completed_at or t.cancelled_at or t.created_at, reverse=True)
        groups.append(("Завершённые", "done", done))
    counts = {
        "active": sum(1 for t in tasks if t.is_open),
        "overdue": sum(1 for t in tasks if t.is_overdue(now)),
        "due_today": sum(1 for t in tasks if t.is_open and t.due_at.date() == now.date()),
        "done": sum(1 for t in tasks if t.status == "done"),
        "early": sum(1 for t in tasks if t.is_early),
    }
    return render(request, "tasks/my.html", active="my_tasks", title="Мои задачи", show=show, counts=counts,
                  groups=[(title, code, enrich(s, items)) for title, code, items in groups], me=user)


# ---------------------------------------------------------------- create / edit (modal)

def default_values() -> dict:
    tomorrow = msk.today() + timedelta(days=1)
    return {"priority": "normal", "due_date": f.fmt_date(tomorrow), "due_time": "18:00"}


def task_values(s: Session, task: Task) -> dict:
    related = svc.related_of(s, task)
    return {"title": task.title, "description": task.description, "assignee_id": str(task.assignee_id),
            "priority": task.priority, "due_date": f.fmt_date(task.due_at.date()),
            "due_time": task.due_at.strftime("%H:%M"), "related": related["value"] if related else "",
            "related_label": f"{related['type']}: {related['name']}" if related else ""}


def form_response(request, s, values, errors, task: Optional[Task] = None, status_code: int = 200):
    ctx = dict(v=values, errors=errors, task=task, managers=managers(s), active="tasks",
               title="Редактирование задачи" if task else "Новая задача")
    if is_htmx(request):
        # 200 even with errors: htmx swaps only 2xx responses, the form stays open with inline messages.
        return render(request, "tasks/_form.html", **ctx)
    return render(request, "tasks/form_page.html", status_code=status_code, **ctx)


def related_label(s: Session, value: str) -> str:
    kind, _, ident = (value or "").partition(":")
    model = svc.RELATED_MODELS.get(kind)
    obj = s.get(model, int(ident)) if model and ident.isdigit() else None
    if obj is None:
        return ""
    return f"{svc.RELATED_TYPE[kind]}: {obj.full_name if kind == 'member' else obj.name}"


@router.get("/new")
def task_new(request: Request, s: Session = Depends(get_session), _=Depends(require("tasks"))):
    return form_response(request, s, default_values(), {})


@router.post("/new")
async def task_create(request: Request, s: Session = Depends(get_session), _=Depends(require("tasks"))):
    user = actor(request, s)
    form = await request.form()
    data, errors = svc.validate(form, s, msk.now())
    if errors:
        values = dict(form)
        values["related_label"] = related_label(s, values.get("related", ""))
        return form_response(request, s, values, errors, status_code=400)
    task = svc.create(s, user, data, msk.now())
    s.commit()
    text = f"Задача создана и назначена: {task.assignee.name}."
    if is_htmx(request):
        return triggers(HTMLResponse(""), closeModal=True, tasksChanged=True, toast={"text": "Задача создана", "kind": "success"})
    return redirect(f"/tasks/{task.id}", text)


@router.get("/{tid}/edit")
def task_edit(tid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("tasks"))):
    user = actor(request, s)
    task = get_task(s, tid, user)
    if not task.is_open:
        return redirect(f"/tasks/{task.id}", "Выполненную или отменённую задачу изменить нельзя.", "error")
    return form_response(request, s, task_values(s, task), {}, task)


@router.post("/{tid}/edit")
async def task_update(tid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("tasks"))):
    user = actor(request, s)
    task = get_task(s, tid, user)
    form = await request.form()
    data, errors = svc.validate(form, s, msk.now())
    if errors:
        values = dict(form)
        values["related_label"] = related_label(s, values.get("related", ""))
        return form_response(request, s, values, errors, task, status_code=400)
    try:
        svc.update(s, task, user, data, msk.now())
    except svc.TaskError as exc:
        return form_response(request, s, dict(form), {"title": str(exc)}, task, status_code=400)
    s.commit()
    if is_htmx(request):
        return triggers(HTMLResponse(""), closeModal=True, closePanel=True, tasksChanged=True,
                        toast={"text": "Изменения сохранены", "kind": "success"})
    return redirect(f"/tasks/{task.id}", "Изменения сохранены.")


# ---------------------------------------------------------------- related entity search

@router.get("/related-search")
def related_search(request: Request, rq: str = "", s: Session = Depends(get_session), _=Depends(require("tasks"))):
    needle = rq.strip().lower().replace("ё", "е")[:100]
    items = []
    t_stmt = select(Tournament).order_by(Tournament.start_date.desc())
    c_stmt = select(Club).order_by(Club.name)
    if needle:
        t_stmt = t_stmt.where(func.py_lower(Tournament.name).contains(needle))
        c_stmt = c_stmt.where(func.py_lower(Club.name).contains(needle))
        members = s.scalars(select(Member).where(
            func.py_lower(Member.last_name + " " + Member.first_name + " " + Member.middle_name).contains(needle)
            | func.py_lower(Member.license_number).contains(needle)
        ).order_by(Member.last_name.collate("ru")).limit(6))
        items += [("member", m.id, m.full_name, "Игрок") for m in members]
    else:
        t_stmt = t_stmt.where(Tournament.status.in_(("registration", "in_progress", "draft")))
    items = [("tournament", t.id, t.name, "Турнир") for t in s.scalars(t_stmt.limit(5))] + items
    items += [("club", c.id, c.name, "Клуб") for c in s.scalars(c_stmt.limit(4))]
    return render(request, "tasks/_related_options.html", items=items, q=rq)


# ---------------------------------------------------------------- detail, panel, actions

def detail_ctx(s: Session, task: Task, user: User) -> dict:
    now = msk.now()
    return dict(task=task, me=user, related=svc.related_of(s, task), overdue=task.is_overdue(now),
                left=svc.humanize(abs(task.due_at - now)), timing=svc.timing_text(task),
                fmt_dt=svc.fmt_dt)


@router.get("/{tid}")
def task_page(tid: int, request: Request, s: Session = Depends(get_session)):
    user = actor(request, s)
    task = get_task(s, tid, user)
    return render(request, "tasks/detail.html", active="tasks" if user.is_director else "my_tasks",
                  title=task.title, **detail_ctx(s, task, user))


@router.get("/{tid}/panel")
def task_panel(tid: int, request: Request, s: Session = Depends(get_session)):
    user = actor(request, s)
    task = get_task(s, tid, user)
    return render(request, "tasks/_panel.html", **detail_ctx(s, task, user))


async def _act(request: Request, s: Session, tid: int, action: str):
    user = actor(request, s)
    task = get_task(s, tid, user)
    now = msk.now()
    try:
        if action == "start":
            svc.start(s, task, user, now)
            message = "Задача взята в работу"
        elif action == "complete":
            form = await request.form()
            svc.complete(s, task, user, form.get("comment", ""), now)
            message = "Задача выполнена" + (" досрочно" if task.is_early else "") + ". Директор получил уведомление."
        else:
            svc.cancel(s, task, user, now)
            message = "Задача отменена. Исполнитель получил уведомление."
    except svc.TaskError as exc:
        if is_htmx(request):
            return triggers(Response(status_code=204), toast={"text": str(exc), "kind": "error"})
        return redirect(f"/tasks/{task.id}", str(exc), "error")
    s.commit()
    if is_htmx(request):
        response = render(request, "tasks/_detail.html", **detail_ctx(s, task, user))
        return triggers(response, tasksChanged=True, toast={"text": message, "kind": "success"})
    return redirect(back_url(request, f"/tasks/{task.id}"), message)


@router.post("/{tid}/start")
async def task_start(tid: int, request: Request, s: Session = Depends(get_session)):
    return await _act(request, s, tid, "start")


@router.post("/{tid}/complete")
async def task_complete(tid: int, request: Request, s: Session = Depends(get_session)):
    return await _act(request, s, tid, "complete")


@router.post("/{tid}/cancel")
async def task_cancel(tid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("tasks"))):
    return await _act(request, s, tid, "cancel")
