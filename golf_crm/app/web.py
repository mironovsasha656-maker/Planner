"""Shared web helpers: templates, demo roles, access control, flash messages."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import labels
from app.services import formatting as f

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

NAV = [
    ("dashboard", "/", "Дашборд", "home"),
    ("players", "/players", "Игроки", "users"),
    ("clubs", "/clubs", "Клубы и поля", "flag"),
    ("tournaments", "/tournaments", "Турниры", "trophy"),
    ("handicap", "/handicap", "Гандикап", "chart"),
    ("finance", "/finance", "Финансы", "wallet"),
    ("officials", "/officials", "Судьи и тренеры", "whistle"),
    ("mailings", "/mailings", "Рассылки", "mail"),
    ("audit", "/audit", "Журнал действий", "list"),
]


def get_role(request: Request) -> str:
    role = request.cookies.get("role", "admin")
    return role if role in ACCESS else "admin"


def can(request: Request, section: str, write: bool = False) -> bool:
    level = ACCESS[get_role(request)].get(section)
    if level is None:
        return False
    return level == "rw" if write else True


def require(section: str, write: bool = False):
    """FastAPI dependency factory enforcing demo role access."""

    def dependency(request: Request) -> str:
        if not can(request, section, write):
            raise HTTPException(status_code=403)
        return get_role(request)

    return dependency


def render(request: Request, template: str, status_code: int = 200, **context):
    role = get_role(request)
    flash = None
    raw = request.cookies.get("flash")
    if raw:
        kind, _, text = unquote(raw).partition("|")
        flash = {"kind": kind, "text": text}
    ctx = {
        "request": request,
        "role": role,
        "can": lambda section, write=False: can(request, section, write),
        "nav": [n for n in NAV if n[0] in ACCESS[role]],
        "today": date.today(),
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
