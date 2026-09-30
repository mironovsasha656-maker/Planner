from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_session
from app.labels import OFFICIAL_ROLE
from app.models import Club, Official
from app.services import audit
from app.services import formatting as f
from app.web import redirect, render, require

router = APIRouter(prefix="/officials")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("")
def officials_list(request: Request, s: Session = Depends(get_session), _=Depends(require("officials"))):
    role = request.query_params.get("role", "")
    stmt = select(Official).order_by(Official.cert_expiry)
    if role in OFFICIAL_ROLE:
        stmt = stmt.where(Official.role == role)
    officials = list(s.scalars(stmt))
    return render(request, "officials/list.html", active="officials", title="Судьи и тренеры",
                  officials=officials, role_filter=role, warn_days=config.CERT_WARNING_DAYS,
                  expiring=sum(1 for o in officials if 0 <= o.days_to_expiry < config.CERT_WARNING_DAYS),
                  expired=sum(1 for o in officials if o.days_to_expiry < 0))


def values_of(o: Official | None) -> dict:
    if o is None:
        return {"role": "referee"}
    return {"full_name": o.full_name, "role": o.role, "qualification": o.qualification,
            "cert_expiry": f.fmt_date(o.cert_expiry), "phone": o.phone, "email": o.email,
            "club_id": str(o.club_id or "")}


def form(request, s, o, v, e, code=200):
    clubs = list(s.scalars(select(Club).order_by(Club.name)))
    return render(request, "officials/form.html", status_code=code, active="officials",
                  title="Судья / тренер", o=o, v=v, errors=e, clubs=clubs)


def validate(data, s: Session):
    v = {k: (data.get(k) or "").strip() for k in ("full_name", "role", "qualification", "cert_expiry", "phone",
                                                    "email", "club_id")}
    e = {}
    if not v["full_name"]:
        e["full_name"] = "Укажите ФИО."
    elif len(v["full_name"]) > 150:
        e["full_name"] = "Не более 150 символов."
    if v["role"] not in OFFICIAL_ROLE:
        e["role"] = "Выберите роль."
    if not v["qualification"]:
        e["qualification"] = "Укажите квалификационную категорию."
    elif len(v["qualification"]) > 120:
        e["qualification"] = "Не более 120 символов."
    expiry = f.parse_date(v["cert_expiry"])
    if expiry is None:
        e["cert_expiry"] = "Укажите дату окончания аттестации."
    if v["email"] and (not EMAIL_RE.match(v["email"]) or len(v["email"]) > 120):
        e["email"] = "Введите корректный адрес электронной почты."
    if len(v["phone"]) > 30:
        e["phone"] = "Не более 30 символов."
    club = s.get(Club, int(v["club_id"])) if v["club_id"].isdigit() else None
    clean = dict(full_name=v["full_name"], role=v["role"], qualification=v["qualification"], cert_expiry=expiry,
                 phone=v["phone"], email=v["email"], club_id=club.id if club else None)
    return v, clean, e


@router.get("/new")
def official_new(request: Request, s: Session = Depends(get_session), _=Depends(require("officials", True))):
    return form(request, s, None, values_of(None), {})


@router.post("/new")
async def official_create(request: Request, s: Session = Depends(get_session), role=Depends(require("officials", True))):
    v, clean, e = validate(await request.form(), s)
    if e:
        return form(request, s, None, v, e, 400)
    o = Official(**clean)
    s.add(o)
    s.flush()
    audit.log(s, role, "create", "official", o.id, f"Добавлен(а) {OFFICIAL_ROLE[o.role].lower()} {o.full_name}")
    s.commit()
    return redirect("/officials", f"{o.full_name} добавлен(а) в список.")


@router.get("/{oid}/edit")
def official_edit(oid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("officials", True))):
    o = s.get(Official, oid)
    if o is None:
        raise HTTPException(404)
    return form(request, s, o, values_of(o), {})


@router.post("/{oid}/edit")
async def official_update(oid: int, request: Request, s: Session = Depends(get_session),
                          role=Depends(require("officials", True))):
    o = s.get(Official, oid)
    if o is None:
        raise HTTPException(404)
    v, clean, e = validate(await request.form(), s)
    if e:
        return form(request, s, o, v, e, 400)
    old_expiry = o.cert_expiry
    for k, val in clean.items():
        setattr(o, k, val)
    text = f"Изменены данные: {o.full_name}"
    if old_expiry != o.cert_expiry:
        text += f" (аттестация: {f.fmt_date(old_expiry)} → {f.fmt_date(o.cert_expiry)})"
    audit.log(s, role, "update", "official", o.id, text)
    s.commit()
    return redirect("/officials", "Изменения сохранены.")
