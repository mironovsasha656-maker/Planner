"""Shared web helpers: templates, demo users and roles, access control, flash messages."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import labels
from app.services import formatting as f
from app.services.users import DEMO_USERS, DIRECTOR_ID, ROLE_DEFAULT_USER
from app import timeutil as msk

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
env = templates.env
env.filters.update(
    date=f.fmt_date,
    datetime=f.fmt_datetime,
    date_long=f.fmt_date_long,
    money=f.fmt_money,
    num=f.fmt_int,
    dec=f.fmt_decimal,
    signed=f.fmt_signed,
)
env.globals.update(L=labels, plural=f.plural)

# Demo roles: which sections each role may open ("r") or change ("rw").
ACCESS: dict[str, dict[str, str]] = {
    "admin": {
        "dashboard": "rw", "players": "rw", "clubs": "rw", "tournaments": "rw", "handicap": "rw",
        "finance": "rw", "officials": "rw", "mailings": "rw", "audit": "r",
    },
    "secretary": {"dashboard": "r", "players": "rw", "clubs": "r", "tournaments": "rw", "handicap": "rw"},
    "accountant": {"dashboard": "r", "players": "r", "finance": "rw"},
}

NAV_GROUPS = [
    ("Основное", [
        ("dashboard", "/", "Дашборд", "home"),
        ("tasks", "/tasks", "Задачи", "check"),
        ("my_tasks", "/tasks/my", "Мои задачи", "check"),
        ("players", "/players", "Игроки", "users"),
        ("clubs", "/clubs", "Клубы и поля", "flag"),
    ]),
    ("Турниры", [
        ("tournaments", "/tournaments", "Турниры", "trophy"),
        ("handicap", "/handicap", "Гандикап", "chart"),
        ("officials", "/officials", "Судьи и тренеры", "whistle"),
    ]),
    ("Финансы", [
        ("finance", "/finance", "Финансы", "wallet"),
    ]),
    ("Коммуникации", [
        ("mailings", "/mailings", "Рассылки", "mail"),
        ("notifications", "/notifications", "Уведомления", "bell"),
        ("audit", "/audit", "Журнал действий", "list"),
    ]),
]
NAV = [item for _, items in NAV_GROUPS for item in items]

# Static copy of the demo users so access checks need no database round trip.
USERS = {uid: {"id": uid, "name": name, "kind": kind, "role": role, "position": position,
               "label": f"{'Директор' if kind == 'director' else 'Менеджер'}: {name}",
               "is_director": kind == "director"}
         for uid, name, kind, role, position in DEMO_USERS}


def current_user_id(request: Request) -> int:
    raw = request.cookies.get("user", "")
    if raw.isdigit() and int(raw) in USERS:
        return int(raw)
    return ROLE_DEFAULT_USER.get(request.cookies.get("role", ""), DIRECTOR_ID)


def current_user(request: Request) -> dict:
    return USERS[current_user_id(request)]


def get_role(request: Request) -> str:
    return current_user(request)["role"]


def can(request: Request, section: str, write: bool = False) -> bool:
    user = current_user(request)
    if section == "tasks":
        return user["is_director"]
    if section == "my_tasks":
        return not user["is_director"]
    if section == "notifications":
        return True
    level = ACCESS[user["role"]].get(section)
    if level is None:
        return False
    return level == "rw" if write else True


def require(section: str, write: bool = False):
    """FastAPI dependency factory enforcing demo access. Returns the actor label for the audit log."""

    def dependency(request: Request) -> str:
        if not can(request, section, write):
            raise HTTPException(status_code=403)
        return current_user(request)["label"]

    return dependency


def render(request: Request, template: str, status_code: int = 200, **context):
    role = get_role(request)
    flash = None
    raw = request.cookies.get("flash")
    if raw:
        kind, _, text = unquote(raw).partition("|")
        flash = {"kind": kind, "text": text}
    user = current_user(request)
    nav_groups = []
    for title, items in NAV_GROUPS:
        visible = [item for item in items if can(request, item[0])]
        if visible:
            nav_groups.append((title, visible))
    ctx = {
        "request": request,
        "role": role,
        "user": user,
        "users": list(USERS.values()),
        "can": lambda section, write=False: can(request, section, write),
        "nav_groups": nav_groups,
        "nav": [item for _, items in nav_groups for item in items],
        "today": msk.today(),
        "now": msk.now(),
        "flash": flash,
        "is_htmx": request.headers.get("HX-Request") == "true",
    }
    ctx.update(context)
    response = templates.TemplateResponse(request, template, ctx, status_code=status_code)
    if raw:
        response.delete_cookie("flash")
    return response


def redirect(url: str, message: Optional[str] = None, kind: str = "success") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if message:
        response.set_cookie("flash", quote(f"{kind}|{message}"), max_age=60, httponly=True, samesite="lax")
    return response


def back_url(request: Request, default: str = "/") -> str:
    """Same-site return URL from the Referer header (never an external redirect)."""
    ref = request.headers.get("referer", "")
    host = request.headers.get("host", "")
    for prefix in (f"http://{host}", f"https://{host}"):
        if host and ref.startswith(prefix):
            path = ref[len(prefix):]
            if path.startswith("/") and not path.startswith("//"):
                return path
    return default


def query_string(params: dict, **overrides) -> str:
    merged = {**params, **overrides}
    clean = {k: v for k, v in merged.items() if v not in (None, "")}
    return urlencode(clean)


env.globals.update(query_string=query_string)
