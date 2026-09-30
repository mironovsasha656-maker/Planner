from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_session
from app.labels import AUDIT_ACTIONS, ENTITY_TYPES, ROLES
from app.models import AuditLog
from app.web import render, require

router = APIRouter(prefix="/audit")

ENTITY_LINKS = {"member": "/players/{}", "tournament": "/tournaments/{}", "message": "/mailings/{}",
                "club": "/clubs/{}"}


@router.get("")
def audit_page(request: Request, s: Session = Depends(get_session), _=Depends(require("audit"))):
    q = request.query_params
    params = {"user": q.get("user", ""), "action": q.get("action", "")}
    stmt = select(AuditLog)
    if params["user"] in ROLES.values():
        stmt = stmt.where(AuditLog.user == params["user"])
    if params["action"] in AUDIT_ACTIONS:
        stmt = stmt.where(AuditLog.action == params["action"])
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    pages = max(1, math.ceil(total / config.PAGE_SIZE))
    page = q.get("page", "1")
    page = min(max(int(page) if page.isdigit() else 1, 1), pages)
    entries = list(s.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                             .offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)))
    ctx = dict(active="audit", title="Журнал действий", entries=entries, params=params, total=total, page=page,
               pages=pages, users=list(ROLES.values()), links=ENTITY_LINKS, entity_types=ENTITY_TYPES)
    if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "results":
        return render(request, "audit/_table.html", **ctx)
    return render(request, "audit/index.html", **ctx)
