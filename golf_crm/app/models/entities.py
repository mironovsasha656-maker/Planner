"""ORM models for the federation CRM."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import config
from app.db import Base
from app import timeutil as msk


def age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def age_category(birth: date, on: date) -> str:
    age = age_on(birth, on)
    if age <= config.JUNIOR_MAX_AGE:
        return "junior"
    if age >= config.SENIOR_MIN_AGE:
        return "senior"
    return "adult"


class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    district: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(250))
    contact_person: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(30))
    website: Mapped[str] = mapped_column(String(150), default="")
    holes: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")

    courses: Mapped[list[Course]] = relationship(
        back_populates="club", cascade="all, delete-orphan", order_by="Course.id"
    )
    members: Mapped[list[Member]] = relationship(back_populates="club")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"))
    name: Mapped[str] = mapped_column(String(150))
    holes: Mapped[int] = mapped_column(Integer)  # 9 or 18

    club: Mapped[Club] = relationship(back_populates="courses")
    tees: Mapped[list[CourseTee]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="CourseTee.id"
    )

    def tee(self, color: str) -> Optional[CourseTee]:
        return next((t for t in self.tees if t.color == color), None)

    @property
    def full_name(self) -> str:
        return f"{self.club.name} — {self.name}"


class CourseTee(Base):
    """Rating data for one set of tees (white / yellow / blue / red)."""

    __tablename__ = "course_tees"
    __table_args__ = (UniqueConstraint("course_id", "color"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    color: Mapped[str] = mapped_column(String(10))
    course_rating: Mapped[float] = mapped_column(Float)
    slope_rating: Mapped[int] = mapped_column(Integer)
    par: Mapped[int] = mapped_column(Integer)

    course: Mapped[Course] = relationship(back_populates="tees")


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_name: Mapped[str] = mapped_column(String(60))
    first_name: Mapped[str] = mapped_column(String(60))
    middle_name: Mapped[str] = mapped_column(String(60), default="")
    birth_date: Mapped[date] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(1))  # M / F
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    club_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clubs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    join_date: Mapped[date] = mapped_column(Date)
    handicap_index: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    handicap_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    license_number: Mapped[str] = mapped_column(String(20), unique=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    pd_consent: Mapped[bool] = mapped_column(Boolean, default=False)

    club: Mapped[Optional[Club]] = relationship(back_populates="members")
    rounds: Mapped[list[Round]] = relationship(
        back_populates="member", cascade="all, delete-orphan", order_by="Round.played_on"
    )
    registrations: Mapped[list[Registration]] = relationship(back_populates="member")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="member", order_by="Payment.issued_on.desc()"
    )

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)

    @property
    def short_name(self) -> str:
        initials = "".join(f"{p[0]}." for p in (self.first_name, self.middle_name) if p)
        return f"{self.last_name} {initials}"

    @property
    def age(self) -> int:
        return age_on(self.birth_date, msk.today())

    @property
    def age_category(self) -> str:
        return age_category(self.birth_date, msk.today())


class Round(Base):
    """A scored round used for the (simplified) handicap calculation."""

    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    tee_id: Mapped[int] = mapped_column(ForeignKey("course_tees.id"))
    played_on: Mapped[date] = mapped_column(Date)
    adjusted_gross: Mapped[int] = mapped_column(Integer)
    differential: Mapped[float] = mapped_column(Float)
    result_id: Mapped[Optional[int]] = mapped_column(ForeignKey("results.id"), nullable=True)
    round_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    member: Mapped[Member] = relationship(back_populates="rounds")
    tee: Mapped[CourseTee] = relationship()


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    format: Mapped[str] = mapped_column(String(20))
    categories: Mapped[str] = mapped_column(String(100), default="")  # comma separated codes
    rounds_count: Mapped[int] = mapped_column(Integer, default=1)
    entry_fee: Mapped[int] = mapped_column(Integer, default=0)
    max_participants: Mapped[int] = mapped_column(Integer)
    registration_deadline: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    description: Mapped[str] = mapped_column(Text, default="")

    course: Mapped[Course] = relationship()
    registrations: Mapped[list[Registration]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", order_by="Registration.id"
    )

    @property
    def category_codes(self) -> list[str]:
        return [c for c in self.categories.split(",") if c]

    @property
    def occupied(self) -> int:
        return sum(1 for r in self.registrations if r.status in ("applied", "confirmed"))

    @property
    def waitlist_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == "waitlist")

    @property
    def is_full(self) -> bool:
        return self.occupied >= self.max_participants


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (UniqueConstraint("tournament_id", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    applied_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="applied")
    fee_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    tee: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(20), default="")

    tournament: Mapped[Tournament] = relationship(back_populates="registrations")
    member: Mapped[Member] = relationship(back_populates="registrations")
    result: Mapped[Optional[Result]] = relationship(
        back_populates="registration", cascade="all, delete-orphan", uselist=False
    )


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), unique=True)
    course_handicap: Mapped[int] = mapped_column(Integer, default=0)
    r1: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    r2: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    r3: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    r4: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rounds_played: Mapped[int] = mapped_column(Integer, default=0)
    total_gross: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_net: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stableford_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    registration: Mapped[Registration] = relationship(back_populates="result")

    @property
    def scores(self) -> list[Optional[int]]:
        return [self.r1, self.r2, self.r3, self.r4]


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)  # rubles
    issued_on: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    paid_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    method: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    comment: Mapped[str] = mapped_column(String(250), default="")
    period_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    registration_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("registrations.id"), nullable=True
    )

    member: Mapped[Member] = relationship(back_populates="payments")
    registration: Mapped[Optional[Registration]] = relationship()

    @property
    def date(self) -> date:
        """Payment date shown in lists: payment date if paid, otherwise invoice date."""
        return self.paid_on or self.issued_on


class Official(Base):
    __tablename__ = "officials"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(20))
    qualification: Mapped[str] = mapped_column(String(120))
    cert_expiry: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    club_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clubs.id"), nullable=True)

    club: Mapped[Optional[Club]] = relationship()

    @property
    def days_to_expiry(self) -> int:
        return (self.cert_expiry - msk.today()).days


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    segment: Mapped[str] = mapped_column(String(20))
    segment_param: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    segment_label: Mapped[str] = mapped_column(String(250))
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="sent")
    recipients_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_by: Mapped[str] = mapped_column(String(60))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    user: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(20))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(500))


class User(Base):
    """Demo user (no authentication). kind: director / manager; role maps to section access."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))
    position: Mapped[str] = mapped_column(String(100), default="")

    @property
    def is_director(self) -> bool:
        return self.kind == "director"

    @property
    def label(self) -> str:
        prefix = "Директор" if self.is_director else "Менеджер"
        return f"{prefix}: {self.name}"

    @property
    def initials(self) -> str:
        return "".join(p[0] for p in self.name.split()[:2])


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(15), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completion_comment: Mapped[str] = mapped_column(Text, default="")
    related_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # tournament / member / club
    related_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    creator: Mapped[User] = relationship(foreign_keys=[creator_id])
    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id])

    @property
    def is_open(self) -> bool:
        return self.status in ("new", "in_progress")

    def is_overdue(self, now: Optional[datetime] = None) -> bool:
        """Derived state, never stored: open and past its deadline."""
        return self.is_open and self.due_at < (now or msk.now())

    @property
    def overdue(self) -> bool:
        return self.is_overdue()

    @property
    def is_early(self) -> bool:
        return self.status == "done" and self.completed_at is not None and self.completed_at < self.due_at

    @property
    def display_status(self) -> str:
        """Status code for the UI, including the derived "overdue"."""
        return "overdue" if self.overdue else self.status


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    text: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    recipient: Mapped[User] = relationship()
    task: Mapped[Optional[Task]] = relationship()
