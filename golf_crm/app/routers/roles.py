"""Demo user / role switcher. There is NO real authentication: anyone can pick any user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.labels import ROLES
from app.services import audit
from app.services.users import ROLE_DEFAULT_USER
from app.web import NAV, USERS, back_url, redirect

router = APIRouter()
COOKIE_AGE = 60 * 60 * 24 * 30


def _target_for(request: Request, user: dict) -> str:
    """Stay on the current page if the new user may open it, otherwise go to the dashboard."""
    target = back_url(request)
    section = next((key for key, url, *_ in sorted(NAV, key=lambda n: -len(n[1]))
                    if url != "/" and target.startswith(url)), "dashboard")
    role_ok = section in ("dashboard", "notifications") or section in _sections(user)
    return target if role_ok else "/"


def _sections(user: dict) -> set[str]:
    from app.web import ACCESS

    sections = set(ACCESS[user["role"]])
    sections.add("tasks" if user["is_director"] else "my_tasks")
    return sections


@router.post("/user")
async def switch_user(request: Request, s: Session = Depends(get_session)):
    form = await request.form()
    raw = form.get("user", "")
    user = USERS.get(int(raw)) if raw.isdigit() else None
    if user is None:
        return redirect(back_url(request), "Неизвестный пользователь.", "error")
    audit.log(s, user["label"], "role", "session", None, f"Выполнен вход как «{user['label']}» (демо, без пароля)")
    s.commit()
    response = redirect(_target_for(request, user), f"Вы работаете как «{user['label']}» (демо-режим, без авторизации).",
                        "info")
    response.set_cookie("user", str(user["id"]), max_age=COOKIE_AGE, httponly=True, samesite="lax")
    response.set_cookie("role", user["role"], max_age=COOKIE_AGE, httponly=True, samesite="lax")
    return response


@router.post("/role")
async def switch_role(request: Request, s: Session = Depends(get_session)):
    """Legacy role switch (admin / secretary / accountant) — maps to the default demo user of that role."""
    form = await request.form()
    role = form.get("role", "")
    if role not in ROLES:
        return redirect(back_url(request), "Неизвестная роль.", "error")
    user = USERS[ROLE_DEFAULT_USER[role]]
    audit.log(s, user["label"], "role", "session", None, f"Демо-роль переключена на «{ROLES[role]}»")
    s.commit()
    response = redirect(_target_for(request, user), f"Вы работаете как «{ROLES[role]}» (демо-режим, без авторизации).",
                        "info")
    response.set_cookie("role", role, max_age=COOKIE_AGE, httponly=True, samesite="lax")
    response.delete_cookie("user")
    return response
