from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.db import get_session
from app.labels import MONTHS_SHORT
from app.models import Club, Member, Official, Payment, Task, Tournament
from app.web import can, current_user, render, require
from app import timeutil as msk

router = APIRouter()


def month_starts(today: date, count: int = 12) -> list[date]:
    months = []
    y, m = today.year, today.month
    for _ in range(count):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(months))


def month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def handicap_buckets(values: list[float]) -> list[int]:
    buckets = [0, 0, 0, 0]
    for v in values:
        buckets[min(int(v // 10), 3)] += 1
    return buckets


@router.get("/")
def dashboard(request: Request, s: Session = Depends(get_session), _=Depends(require("dashboard"))):
    today = msk.today()
    members = list(s.scalars(select(Member)))
    total = len(members)
    active = sum(1 for m in members if m.status == "active")
    unpaid = sum(1 for m in members if m.status == "unpaid")

    upcoming = list(s.scalars(
        select(Tournament)
        .where(Tournament.end_date >= today, Tournament.status.in_(("registration", "in_progress", "draft")))
        .order_by(Tournament.start_date)
    ))

    month_start = today.replace(day=1)
    revenue_month = s.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status == "paid", Payment.paid_on >= month_start, Payment.paid_on <= today)) or 0
    revenue_year = s.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status == "paid", Payment.paid_on >= date(today.year, 1, 1), Payment.paid_on <= today)) or 0

    months = month_starts(today)
    growth = {
        "labels": [f"{MONTHS_SHORT[m.month - 1]} {str(m.year)[2:]}" for m in months],
        "total": [sum(1 for x in members if x.join_date <= month_end(m)) for m in months],
        "new": [sum(1 for x in members if m <= x.join_date <= month_end(m)) for m in months],
    }
    hcp = handicap_buckets([m.handicap_index for m in members if m.handicap_index is not None])

    club_rows = s.execute(
        select(Club, func.count(Member.id).label("n"))
        .outerjoin(Member, Member.club_id == Club.id)
        .group_by(Club.id)
        .order_by(func.count(Member.id).desc())
        .limit(5)
    ).all()

    overdue_payments = list(s.scalars(
        select(Payment).where(Payment.status == "overdue").order_by(Payment.due_date)
    ))
    expiring = list(s.scalars(
        select(Official)
        .where(Official.cert_expiry <= today + timedelta(days=config.CERT_WARNING_DAYS))
        .order_by(Official.cert_expiry)
    ))
    full = [t for t in upcoming if t.status == "registration" and t.is_full]

    now = msk.now()
    user = current_user(request)
    task_stmt = select(Task)
    if not user["is_director"]:
        task_stmt = task_stmt.where(Task.assignee_id == user["id"])
    tasks = list(s.scalars(task_stmt))
    open_tasks = sorted((t for t in tasks if t.is_open), key=lambda t: t.due_at)
    week_ago = now - timedelta(days=7)
    task_summary = {
        "open": len(open_tasks),
        "overdue": [t for t in open_tasks if t.is_overdue(now)],
        "done_week": sum(1 for t in tasks if t.status == "done" and t.completed_at >= week_ago),
        "early_week": sum(1 for t in tasks if t.is_early and t.completed_at >= week_ago),
        "next": [t for t in open_tasks if not t.is_overdue(now)][:4],
    }

    return render(
        request, "dashboard.html", task_summary=task_summary, now=now, active="dashboard", title="Дашборд",
        total=total, active_count=active, unpaid=unpaid, upcoming=upcoming,
        revenue_month=revenue_month, revenue_year=revenue_year, growth=growth, hcp=hcp,
        club_rows=club_rows, overdue_payments=overdue_payments,
        overdue_sum=sum(p.amount for p in overdue_payments), expiring=expiring, full=full,
        show_finance=can(request, "finance"),
    )
