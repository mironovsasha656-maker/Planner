"""Mailings. Sending is SIMULATED: recipients are written to logs/mailings.log, nothing is sent."""
from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_session
from app.labels import ROLES, SEGMENTS
from app.models import Club, Message, Tournament
from app.services import audit
from app.services.segmentation import SegmentError, resolve
from app.web import get_role, redirect, render, require

router = APIRouter(prefix="/mailings")


def mail_logger() -> logging.Logger:
    logger = logging.getLogger("golf_crm.mailings")
    if not logger.handlers:
        config.LOG_DIR.mkdir(exist_ok=True)
        handler = logging.FileHandler(config.LOG_DIR / "mailings.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def segment_param(form) -> tuple[str, int | None]:
    segment = form.get("segment") or ""
    key = {"club": "club_id", "tournament": "tournament_id"}.get(segment)
    raw = (form.get(key) or "") if key else ""
    return segment, int(raw) if raw.isdigit() else None


def choices(s: Session):
    clubs = list(s.scalars(select(Club).order_by(Club.name)))
    tournaments = list(s.scalars(select(Tournament).where(Tournament.status != "draft")
                                 .order_by(Tournament.start_date.desc())))
    return clubs, tournaments


@router.get("")
def mailings_list(request: Request, s: Session = Depends(get_session), _=Depends(require("mailings"))):
    messages = list(s.scalars(select(Message).order_by(Message.sent_at.desc())))
    return render(request, "mailings/list.html", active="mailings", title="Рассылки", messages=messages)


@router.get("/new")
def mailing_new(request: Request, s: Session = Depends(get_session), _=Depends(require("mailings", True))):
    clubs, tournaments = choices(s)
    segment = request.query_params.get("segment", "all")
    v = {"segment": segment if segment in SEGMENTS else "all", "subject": "", "body": ""}
    return render(request, "mailings/form.html", active="mailings", title="Новая рассылка", v=v, errors={},
                  clubs=clubs, tournaments=tournaments, preview=preview_data(s, v["segment"], None))


def preview_data(s: Session, segment: str, param: int | None):
    try:
        return {"result": resolve(s, segment, param, date.today()), "error": None}
    except SegmentError as exc:
        return {"result": None, "error": str(exc)}


@router.get("/preview")
def mailing_preview(request: Request, s: Session = Depends(get_session), _=Depends(require("mailings", True))):
    segment, param = segment_param(request.query_params)
    return render(request, "mailings/_preview.html", preview=preview_data(s, segment, param))


@router.post("/new")
async def mailing_send(request: Request, s: Session = Depends(get_session), role=Depends(require("mailings", True))):
    form = await request.form()
    segment, param = segment_param(form)
    v = {"segment": segment, "subject": (form.get("subject") or "").strip(), "body": (form.get("body") or "").strip(),
         "club_id": form.get("club_id") or "", "tournament_id": form.get("tournament_id") or ""}
    errors = {}
    if not v["subject"]:
        errors["subject"] = "Укажите тему письма."
    elif len(v["subject"]) > 200:
        errors["subject"] = "Тема — не более 200 символов."
    if not v["body"]:
        errors["body"] = "Введите текст сообщения."
    elif len(v["body"]) > 5000:
        errors["body"] = "Текст — не более 5000 символов."
    preview = preview_data(s, segment, param)
    if preview["error"]:
        errors["segment"] = preview["error"]
    elif not preview["result"].recipients:
        errors["segment"] = "В выбранном сегменте нет получателей с согласием на обработку ПДн и e-mail."
    if errors:
        clubs, tournaments = choices(s)
        return render(request, "mailings/form.html", status_code=400, active="mailings", title="Новая рассылка",
                      v=v, errors=errors, clubs=clubs, tournaments=tournaments, preview=preview)
    result = preview["result"]
    msg = Message(subject=v["subject"], body=v["body"], segment=segment, segment_param=param,
                  segment_label=result.label, sent_at=datetime.now().replace(microsecond=0), status="sent",
                  recipients_count=len(result.recipients), sent_by=ROLES[get_role(request)])
    s.add(msg)
    s.flush()
    log = mail_logger()
    log.info("MAILING #%s (SIMULATED, NOT SENT) subject=%r segment=%r recipients=%d",
             msg.id, msg.subject, msg.segment_label, msg.recipients_count)
    for m in result.recipients:
        log.info("  -> %s <%s>", m.full_name, m.email)
    audit.log(s, role, "mailing", "message", msg.id,
              f"Рассылка «{msg.subject}» (сегмент: {msg.segment_label}), получателей: {msg.recipients_count}")
    s.commit()
    return redirect(f"/mailings/{msg.id}",
                    f"Рассылка «отправлена» (имитация): {msg.recipients_count} получателей. Письма не отправлялись — "
                    "список записан в журнал.")


@router.get("/{mid}")
def mailing_detail(mid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("mailings"))):
    msg = s.get(Message, mid)
    if msg is None:
        raise HTTPException(404)
    return render(request, "mailings/detail.html", active="mailings", title=msg.subject, msg=msg)
