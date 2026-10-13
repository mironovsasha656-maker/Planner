"""In-app notifications (bell in the top bar). Delivery is in-app only — no e-mail/SMS."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import timeutil as msk
from app.db import get_session
from app.models import Notification
from app.services import tasks as svc
from app.web import back_url, current_user_id, redirect, render

router = APIRouter(prefix="/notifications")


def _url(n: Notification) -> str:
    return f"/notifications/{n.id}/open"


@router.get("/poll")
def poll(request: Request, since: str = "-1", s: Session = Depends(get_session)):
    """Unread badge + HX-Trigger "newNotifications" with toasts for notifications newer than `since`.

    since = -1 means "first load for this user in this browser tab": only report the latest id.
    """
    uid = current_user_id(request)
    if svc.sync_overdue(s, msk.now()):
        s.commit()
    unread = s.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_id == uid, Notification.is_read.is_(False))) or 0
    latest = s.scalar(select(func.max(Notification.id)).where(Notification.recipient_id == uid)) or 0
    items = []
    try:
        since_id = int(since)
    except ValueError:
        since_id = -1
    if since_id >= 0:
        fresh = s.scalars(select(Notification).where(
            Notification.recipient_id == uid, Notification.id > since_id, Notification.is_read.is_(False)
        ).order_by(Notification.id.desc()).limit(3))
        items = [{"text": n.text, "url": _url(n),
                  "kind": "error" if n.type == "task_overdue" else "success" if n.type == "task_completed" else "info"}
                 for n in fresh]
    body = f'<span class="dot" aria-label="Непрочитанных: {unread}">{unread if unread < 100 else "99+"}</span>' if unread else ""
    response = HTMLResponse(body)
    response.headers["HX-Trigger"] = json.dumps({"newNotifications": {"items": items, "latest": latest}},
                                                ensure_ascii=True)
    return response


@router.get("/menu")
def menu(request: Request, s: Session = Depends(get_session)):
    uid = current_user_id(request)
    items = list(s.scalars(select(Notification).where(Notification.recipient_id == uid)
                           .order_by(Notification.id.desc()).limit(8)))
    unread = s.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_id == uid, Notification.is_read.is_(False))) or 0
    return render(request, "notifications/_menu.html", items=items, unread=unread)


@router.get("")
def page(request: Request, s: Session = Depends(get_session)):
    uid = current_user_id(request)
    show = request.query_params.get("show", "all")
    stmt = select(Notification).where(Notification.recipient_id == uid)
    if show == "unread":
        stmt = stmt.where(Notification.is_read.is_(False))
    items = list(s.scalars(stmt.order_by(Notification.id.desc()).limit(200)))
    unread = s.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_id == uid, Notification.is_read.is_(False))) or 0
    return render(request, "notifications/index.html", active="notifications", title="Уведомления",
                  items=items, unread=unread, show=show)


@router.post("/read-all")
def read_all(request: Request, s: Session = Depends(get_session)):
    uid = current_user_id(request)
    s.execute(update(Notification).where(Notification.recipient_id == uid, Notification.is_read.is_(False))
              .values(is_read=True))
    s.commit()
    return redirect(back_url(request, "/notifications"), "Все уведомления отмечены как прочитанные.")


@router.get("/{nid}/open")
def open_notification(nid: int, request: Request, s: Session = Depends(get_session)):
    n = s.get(Notification, nid)
    if n is None or n.recipient_id != current_user_id(request):
        raise HTTPException(404)
    n.is_read = True
    s.commit()
    return redirect(f"/tasks/{n.task_id}" if n.task_id else "/notifications")
