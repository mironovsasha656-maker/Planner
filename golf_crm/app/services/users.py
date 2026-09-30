"""Demo users. There is NO authentication: the current user is picked in the header.

Each user maps onto one of the existing access roles (admin / secretary / accountant).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

# id, name, kind, access role, position
DEMO_USERS = [
    (1, "Ольга Кравцова", "director", "admin", "Директор Федерации"),
    (2, "Иван Петров", "manager", "secretary", "Менеджер по турнирам"),
    (3, "Мария Соколова", "manager", "accountant", "Менеджер по финансам"),
    (4, "Алексей Волков", "manager", "secretary", "Менеджер по работе с клубами"),
]
FEMALE = {1, 3}  # for grammatical gender in notification texts


def verb(user, masculine: str) -> str:
    """Past-tense verb agreeing with the user: "выполнил" -> "выполнила"."""
    return masculine + "а" if user.id in FEMALE else masculine
DIRECTOR_ID = 1
# Legacy role cookie -> the demo user acting in that role.
ROLE_DEFAULT_USER = {"admin": 1, "secretary": 2, "accountant": 3}


def ensure_users(session: Session) -> None:
    """Create the demo users if they are missing (idempotent, also for older databases)."""
    existing = set(session.scalars(select(User.id)))
    for uid, name, kind, role, position in DEMO_USERS:
        if uid not in existing:
            session.add(User(id=uid, name=name, kind=kind, role=role, position=position))
    session.flush()


def managers(session: Session) -> list[User]:
    return list(session.scalars(select(User).where(User.kind == "manager").order_by(User.id)))


def all_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


def resolve(session: Session, user_cookie: Optional[str], role_cookie: Optional[str]) -> User:
    user = session.get(User, int(user_cookie)) if user_cookie and user_cookie.isdigit() else None
    if user is None:
        user = session.get(User, ROLE_DEFAULT_USER.get(role_cookie or "", DIRECTOR_ID))
    if user is None:  # database without demo users
        ensure_users(session)
        session.commit()
        user = session.get(User, DIRECTOR_ID)
    return user
