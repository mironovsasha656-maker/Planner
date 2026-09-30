"""Demo role switcher. There is NO real authentication: anyone can pick any role."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.labels import ROLES
from app.services import audit
from app.web import ACCESS, NAV, back_url, redirect

router = APIRouter()


@router.post("/role")
async def switch_role(request: Request, s: Session = Depends(get_session)):
    form = await request.form()
    role = form.get("role", "")
    if role not in ROLES:
        return redirect(back_url(request), "Неизвестная роль.", "error")
    target = back_url(request)
    # If the current page is not available for the new role, go to the dashboard.
    section = next((key for key, url, *_ in NAV if url != "/" and target.startswith(url)), "dashboard")
    if section not in ACCESS[role]:
        target = "/"
    audit.log(s, role, "role", "session", None, f"Демо-роль переключена на «{ROLES[role]}»")
    s.commit()
    response = redirect(target, f"Вы работаете как «{ROLES[role]}» (демо-режим, без авторизации).", "info")
    response.set_cookie("role", role, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return response
