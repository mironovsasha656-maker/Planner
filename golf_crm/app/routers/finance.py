from __future__ import annotations

import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app import config
from app.db import get_session
from app.labels import MONTHS_SHORT, PAYMENT_METHOD, PAYMENT_STATUS, PAYMENT_TYPE
from app.models import Member, Payment
from app.routers.dashboard import month_end, month_starts
from app.services import audit
from app.services import formatting as f
from app.services import payments as pay
from app.web import back_url, redirect, render, require
from app import timeutil as msk

router = APIRouter(prefix="/finance")


def read_filters(request: Request) -> dict:
    q = request.query_params
    return {
        "q": (q.get("q") or "").strip()[:100],
        "type": q.get("type") or "",
        "status": q.get("status") or "",
        "method": q.get("method") or "",
        "date_from": q.get("date_from") or "",
        "date_to": q.get("date_to") or "",
    }


def filtered_query(params: dict):
    stmt = select(Payment).join(Member).options(selectinload(Payment.member))
    if params["q"]:
        needle = params["q"].lower().replace("ё", "е")
        stmt = stmt.where(
            func.py_lower(Member.last_name + " " + Member.first_name + " " + Member.middle_name).contains(needle)
            | func.py_lower(Member.license_number).contains(needle)
            | func.py_lower(Payment.comment).contains(needle)
        )
    if params["type"] in PAYMENT_TYPE:
        stmt = stmt.where(Payment.type == params["type"])
    if params["status"] in PAYMENT_STATUS:
        stmt = stmt.where(Payment.status == params["status"])
    if params["method"] in PAYMENT_METHOD:
        stmt = stmt.where(Payment.method == params["method"])
    shown_date = func.coalesce(Payment.paid_on, Payment.issued_on)
    d_from, d_to = f.parse_date(params["date_from"]), f.parse_date(params["date_to"])
    if d_from:
        stmt = stmt.where(shown_date >= d_from)
    if d_to:
        stmt = stmt.where(shown_date <= d_to)
    return stmt.order_by(shown_date.desc(), Payment.id.desc())


def debtors(s: Session, year: int):
    stmt = (
        select(Payment).join(Member)
        .where(Payment.type == "membership", Payment.period_year == year, Payment.status.in_(("pending", "overdue")))
        .options(selectinload(Payment.member).selectinload(Member.club))
        .order_by(case((Payment.status == "overdue", 0), else_=1), Payment.due_date, Member.last_name.collate("ru"))
    )
    return list(s.scalars(stmt))


def monthly_summary(s: Session, today: date):
    months = month_starts(today)
    paid = list(s.scalars(select(Payment).where(
        Payment.status == "paid", Payment.paid_on >= months[0], Payment.paid_on <= today)))
    rows = []
    for m in months:
        end = month_end(m)
        in_month = [p for p in paid if m <= p.paid_on <= end]
        by_type = {t: sum(p.amount for p in in_month if p.type == t) for t in PAYMENT_TYPE}
        rows.append({"month": m, "label": f"{MONTHS_SHORT[m.month - 1]} {m.year}", "by_type": by_type,
                     "total": sum(by_type.values()), "count": len(in_month)})
    return rows


@router.get("")
def finance_page(request: Request, s: Session = Depends(get_session), _=Depends(require("finance"))):
    today = msk.today()
    tab = request.query_params.get("tab", "payments")
    if tab not in ("payments", "debtors", "summary"):
        tab = "payments"
    ctx = dict(active="finance", title="Финансы", tab=tab, fees=config.MEMBERSHIP_FEES)
    outstanding = s.execute(select(Payment.status, func.count(), func.sum(Payment.amount))
                            .where(Payment.status.in_(("pending", "overdue"))).group_by(Payment.status)).all()
    ctx["outstanding"] = {st: (n, total) for st, n, total in outstanding}
    ctx["debtor_count"] = len(debtors(s, today.year))
    if tab == "payments":
        params = read_filters(request)
        stmt = filtered_query(params)
        total = s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        pages = max(1, math.ceil(total / config.PAGE_SIZE))
        page = request.query_params.get("page", "1")
        page = min(max(int(page) if page.isdigit() else 1, 1), pages)
        payments = list(s.scalars(stmt.offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)))
        sum_total = s.scalar(select(func.coalesce(func.sum(stmt.subquery().c.amount), 0)))
        ctx.update(params=params, payments=payments, total=total, pages=pages, page=page, sum_total=sum_total)
        if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "results":
            return render(request, "finance/_payments.html", **ctx)
    elif tab == "debtors":
        ctx["debtors"] = debtors(s, today.year)
    else:
        rows = monthly_summary(s, today)
        ctx["rows"] = rows
        ctx["chart"] = {
            "labels": [r["label"] for r in rows],
            "series": [{"label": PAYMENT_TYPE[t], "data": [r["by_type"][t] for r in rows]} for t in PAYMENT_TYPE],
        }
        ctx["year_total"] = sum(r["total"] for r in rows)
    return render(request, "finance/index.html", **ctx)


@router.get("/export.csv")
def finance_export(request: Request, s: Session = Depends(get_session), role=Depends(require("finance"))):
    params = read_filters(request)
    payments = list(s.scalars(filtered_query(params)))
    rows = [
        (p.id, p.member.full_name, p.member.license_number, PAYMENT_TYPE[p.type], p.comment, p.amount,
         f.fmt_date(p.issued_on), f.fmt_date(p.due_date), f.fmt_date(p.paid_on) if p.paid_on else "",
         PAYMENT_METHOD[p.method], PAYMENT_STATUS[p.status])
        for p in payments
    ]
    data = f.to_csv(["№", "Плательщик", "Лицензия", "Тип", "Назначение", "Сумма, ₽", "Выставлен", "Срок оплаты",
                     "Дата оплаты", "Способ", "Статус"], rows)
    audit.log(s, role, "export", "payment", None, f"Экспорт платежей в CSV ({len(rows)} записей)")
    s.commit()
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="payments_{msk.today():%Y%m%d}.csv"'})


@router.post("/payments/{pid}/paid")
async def mark_paid(pid: int, request: Request, s: Session = Depends(get_session), role=Depends(require("finance", True))):
    p = s.get(Payment, pid)
    if p is None:
        raise HTTPException(404)
    back = back_url(request, "/finance")
    if p.status == "paid":
        return redirect(back, f"Платёж №{p.id} уже оплачен.", "info")
    form = await request.form()
    method = form.get("method") if form.get("method") in PAYMENT_METHOD else None
    was_unpaid = p.member.status == "unpaid"
    pay.mark_paid(p, msk.today(), method)
    msg = f"Платёж №{p.id} ({p.member.full_name}, {f.fmt_money(p.amount)}) отмечен как оплаченный."
    if was_unpaid and p.member.status == "active":
        msg += " Статус игрока изменён на «Активен»."
    audit.log(s, role, "payment", "payment", p.id, msg)
    s.commit()
    return redirect(back, msg)


# ---------------------------------------------------------------- new payment

def payment_form(request, s, values, errors, status_code=200):
    members = list(s.scalars(select(Member).order_by(Member.last_name.collate("ru"), Member.first_name)))
    return render(request, "finance/form.html", status_code=status_code, active="finance", title="Новый платёж",
                  v=values, errors=errors, members=members, fees=config.MEMBERSHIP_FEES)


@router.get("/payments/new")
def payment_new(request: Request, s: Session = Depends(get_session), _=Depends(require("finance", True))):
    today = msk.today()
    values = {"type": "membership", "issued_on": f.fmt_date(today),
              "due_date": f.fmt_date(today + timedelta(days=config.MEMBERSHIP_PAYMENT_TERM_DAYS)),
              "method": "invoice", "status": "pending", "member_id": request.query_params.get("member", "")}
    return payment_form(request, s, values, {})


@router.post("/payments/new")
async def payment_create(request: Request, s: Session = Depends(get_session), role=Depends(require("finance", True))):
    form = await request.form()
    today = msk.today()
    v = {k: (form.get(k) or "").strip() for k in
         ("member_id", "type", "amount", "issued_on", "due_date", "method", "status", "comment")}
    e: dict[str, str] = {}
    member = s.get(Member, int(v["member_id"])) if v["member_id"].isdigit() else None
    if member is None:
        e["member_id"] = "Выберите плательщика."
    if v["type"] not in PAYMENT_TYPE or v["type"] == "tournament":
        e["type"] = "Выберите тип платежа (турнирные взносы выставляются из карточки турнира)."
    amount = None
    if not v["amount"] and member and v["type"] == "membership":
        amount = pay.membership_fee(member, today)
    elif v["amount"].isdigit() and 1 <= int(v["amount"]) <= 1_000_000:
        amount = int(v["amount"])
    else:
        e["amount"] = "Сумма — целое число рублей от 1 до 1 000 000."
    issued, due = f.parse_date(v["issued_on"]), f.parse_date(v["due_date"])
    if issued is None:
        e["issued_on"] = "Укажите дату."
    elif issued > today:
        e["issued_on"] = "Дата не может быть в будущем."
    if due is None:
        e["due_date"] = "Укажите срок оплаты."
    elif issued and due < issued:
        e["due_date"] = "Срок оплаты раньше даты выставления."
    if v["method"] not in PAYMENT_METHOD:
        e["method"] = "Выберите способ оплаты."
    if v["status"] not in ("pending", "paid"):
        e["status"] = "Выберите статус."
    if len(v["comment"]) > 250:
        e["comment"] = "Не более 250 символов."
    if v["type"] == "membership" and member and not e:
        exists = s.scalar(select(Payment.id).where(Payment.member_id == member.id, Payment.type == "membership",
                                                   Payment.period_year == today.year))
        if exists:
            e["type"] = f"Членский взнос за {today.year} год этому игроку уже выставлен (платёж №{exists})."
    if e:
        return payment_form(request, s, v, e, 400)
    p = Payment(member=member, type=v["type"], amount=amount, issued_on=issued, due_date=due, method=v["method"],
                status="pending", comment=v["comment"] or (f"Членский взнос за {today.year} год" if v["type"] == "membership" else ""),
                period_year=today.year if v["type"] == "membership" else None)
    s.add(p)
    s.flush()
    if v["status"] == "paid":
        pay.mark_paid(p, issued)
    elif due < today:
        p.status = "overdue"
        if p.type == "membership" and member.status == "active":
            member.status = "unpaid"
    audit.log(s, role, "create", "payment", p.id,
              f"Добавлен платёж №{p.id}: {member.full_name}, {PAYMENT_TYPE[p.type]}, {f.fmt_money(p.amount)}")
    s.commit()
    return redirect("/finance", f"Платёж №{p.id} на сумму {f.fmt_money(p.amount)} добавлен.")
