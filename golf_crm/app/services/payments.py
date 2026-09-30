"""Payment rules: membership fee amounts, marking as paid, overdue refresh.

Payments are simulated: nothing is charged, statuses are changed manually.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Member, Payment, age_category


def membership_fee(member: Member, on: date) -> int:
    return config.MEMBERSHIP_FEES[age_category(member.birth_date, on)]


def has_unpaid_overdue_membership(member: Member) -> bool:
    return any(p.type == "membership" and p.status == "overdue" for p in member.payments)


def mark_paid(payment: Payment, today: date, method: str | None = None) -> None:
    payment.status = "paid"
    payment.paid_on = today
    if method:
        payment.method = method
    if payment.registration is not None:
        payment.registration.fee_paid = True
    member = payment.member
    if payment.type == "membership" and member.status == "unpaid":
        if not has_unpaid_overdue_membership(member):
            member.status = "active"


def refresh_overdue(session: Session, today: date) -> int:
    """Mark pending payments past their due date as overdue; flag membership debtors."""
    stmt = select(Payment).where(Payment.status == "pending", Payment.due_date < today)
    changed = 0
    for payment in session.scalars(stmt):
        payment.status = "overdue"
        changed += 1
        if payment.type == "membership" and payment.member.status == "active":
            payment.member.status = "unpaid"
    return changed
