from __future__ import annotations

import calendar as cal
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.labels import (
    MONTHS,
    REGISTRATION_STATUS,
    SCORING_CATEGORY,
    TEE_COLORS,
    TOURNAMENT_FORMAT,
    TOURNAMENT_STATUS,
    WEEKDAYS_SHORT,
)
from app.models import Club, Course, Member, Payment, Registration, Tournament
from app.services import audit, handicap, leaderboard
from app.services import formatting as f
from app.services import payments as pay
from app.services.registration import (
    RegistrationError,
    change_status,
    promote_after_limit_change,
    register,
)
from app.services.tournaments import TRANSITIONS, post_rounds_to_handicap, round_date
from app.web import redirect, render, require

router = APIRouter()

TABS = ("overview", "registrations", "results", "leaderboard")


def get_tournament(s: Session, tid: int) -> Tournament:
    t = s.get(Tournament, tid)
    if t is None:
        raise HTTPException(404)
    return t


# ---------------------------------------------------------------- list & calendar

@router.get("/tournaments")
def tournaments_list(request: Request, s: Session = Depends(get_session), _=Depends(require("tournaments"))):
    today = date.today()
    view = request.query_params.get("view", "list")
    status = request.query_params.get("status", "")
    stmt = select(Tournament).order_by(Tournament.start_date)
    if status in TOURNAMENT_STATUS:
        stmt = stmt.where(Tournament.status == status)
    tournaments = list(s.scalars(stmt))
    ctx = dict(active="tournaments", title="Турниры", view=view, status=status)

    if view == "calendar":
        month_param = request.query_params.get("month", "")
        try:
            first = datetime.strptime(month_param, "%Y-%m").date()
        except ValueError:
            first = today.replace(day=1)
        weeks = cal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
        events: dict[date, list[Tournament]] = {}
        for t in tournaments:
            d = t.start_date
            while d <= t.end_date:
                events.setdefault(d, []).append(t)
                d += timedelta(days=1)
        prev_month = (first - timedelta(days=1)).replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        ctx.update(first=first, weeks=weeks, events=events, prev_month=prev_month, next_month=next_month,
                   month_label=f"{MONTHS[first.month - 1]} {first.year}", weekdays=WEEKDAYS_SHORT)
    else:
        upcoming = [t for t in tournaments if t.end_date >= today and t.status != "cancelled"]
        past = [t for t in tournaments if t not in upcoming]
        past.reverse()
        ctx.update(upcoming=upcoming, past=past)
    return render(request, "tournaments/list.html", **ctx)


# ---------------------------------------------------------------- create / edit

def courses_for_form(s: Session):
    return list(s.execute(select(Course, Club).join(Club).order_by(Club.name, Course.id)))


def form_values(t: Tournament | None) -> dict:
    if t is None:
        start = date.today() + timedelta(days=30)
        return {"start_date": f.fmt_date(start), "end_date": f.fmt_date(start),
                "registration_deadline": f.fmt_date(start - timedelta(days=5)), "format": "stroke_net",
                "categories": ["men", "women"], "rounds_count": "1", "entry_fee": "3000",
                "max_participants": "60", "status": "draft"}
    return {
        "name": t.name, "start_date": f.fmt_date(t.start_date), "end_date": f.fmt_date(t.end_date),
        "course_id": str(t.course_id), "format": t.format, "categories": t.category_codes,
        "rounds_count": str(t.rounds_count), "entry_fee": str(t.entry_fee),
        "max_participants": str(t.max_participants),
        "registration_deadline": f.fmt_date(t.registration_deadline), "description": t.description,
    }


def validate(form, s: Session, t: Tournament | None) -> tuple[dict, dict]:
    v = {k: (form.get(k) or "").strip() for k in (
        "name", "start_date", "end_date", "course_id", "format", "rounds_count", "entry_fee",
        "max_participants", "registration_deadline", "description", "status")}
    v["categories"] = [c for c in form.getlist("categories") if c in SCORING_CATEGORY]
    e: dict[str, str] = {}
    if not v["name"]:
        e["name"] = "Укажите название турнира."
    elif len(v["name"]) > 150:
        e["name"] = "Не более 150 символов."
    if len(v["description"]) > 2000:
        e["description"] = "Не более 2000 символов."
    start, end = f.parse_date(v["start_date"]), f.parse_date(v["end_date"])
    deadline = f.parse_date(v["registration_deadline"])
    if start is None:
        e["start_date"] = "Укажите дату начала."
    if end is None:
        e["end_date"] = "Укажите дату окончания."
    elif start and end < start:
        e["end_date"] = "Окончание не может быть раньше начала."
    elif start and (end - start).days > 6:
        e["end_date"] = "Турнир не может длиться больше 7 дней."
    if deadline is None:
        e["registration_deadline"] = "Укажите срок подачи заявок."
    elif start and deadline > start:
        e["registration_deadline"] = "Срок подачи заявок должен быть не позже даты начала."
    course = s.get(Course, int(v["course_id"])) if v["course_id"].isdigit() else None
    if course is None:
        e["course_id"] = "Выберите поле."
    elif t is not None and course.id != t.course_id and any(r.result for r in t.registrations):
        e["course_id"] = "Нельзя сменить поле: по турниру уже введены результаты."
    if v["format"] not in TOURNAMENT_FORMAT:
        e["format"] = "Выберите формат."
    rounds = int(v["rounds_count"]) if v["rounds_count"].isdigit() else 0
    if not 1 <= rounds <= 4:
        e["rounds_count"] = "От 1 до 4 раундов."
    elif start and end and rounds > (end - start).days + 1:
        e["rounds_count"] = "Раундов больше, чем игровых дней (не более одного раунда в день)."
    fee = int(v["entry_fee"]) if v["entry_fee"].isdigit() else -1
    if not 0 <= fee <= 100_000:
        e["entry_fee"] = "Взнос — целое число от 0 до 100 000 ₽."
    limit = int(v["max_participants"]) if v["max_participants"].isdigit() else 0
    if not 2 <= limit <= 200:
        e["max_participants"] = "Лимит — от 2 до 200 участников."
    elif t is not None and limit < t.occupied:
        e["max_participants"] = f"Лимит меньше числа уже занятых мест ({t.occupied})."
    if t is None and v["status"] not in ("draft", "registration"):
        e["status"] = "Выберите начальный статус."
    clean = dict(name=v["name"], start_date=start, end_date=end, course_id=course.id if course else None,
                 format=v["format"], categories=",".join(v["categories"]), rounds_count=rounds, entry_fee=fee,
                 max_participants=limit, registration_deadline=deadline, description=v["description"])
    return {"clean": clean, "raw": v}, e


def render_form(request, s, t, values, errors, status_code=200):
    return render(request, "tournaments/form.html", status_code=status_code, active="tournaments",
                  title="Редактирование турнира" if t else "Новый турнир", t=t, v=values, errors=errors,
                  courses=courses_for_form(s))


@router.get("/tournaments/new")
def tournament_new(request: Request, s: Session = Depends(get_session), _=Depends(require("tournaments", True))):
    return render_form(request, s, None, form_values(None), {})


@router.post("/tournaments/new")
async def tournament_create(request: Request, s: Session = Depends(get_session),
                            role=Depends(require("tournaments", True))):
    form = await request.form()
    data, errors = validate(form, s, None)
    if errors:
        return render_form(request, s, None, data["raw"], errors, 400)
    t = Tournament(**data["clean"], status=data["raw"]["status"])
    s.add(t)
    s.flush()
    audit.log(s, role, "create", "tournament", t.id, f"Создан турнир «{t.name}»")
    s.commit()
    return redirect(f"/tournaments/{t.id}", "Турнир создан.")


@router.get("/tournaments/{tid}/edit")
def tournament_edit(tid: int, request: Request, s: Session = Depends(get_session),
                    _=Depends(require("tournaments", True))):
    t = get_tournament(s, tid)
    if t.status in ("finished", "cancelled"):
        return redirect(f"/tournaments/{t.id}", "Завершённый или отменённый турнир редактировать нельзя.", "error")
    return render_form(request, s, t, form_values(t), {})


@router.post("/tournaments/{tid}/edit")
async def tournament_update(tid: int, request: Request, s: Session = Depends(get_session),
                            role=Depends(require("tournaments", True))):
    t = get_tournament(s, tid)
    if t.status in ("finished", "cancelled"):
        return redirect(f"/tournaments/{t.id}", "Завершённый или отменённый турнир редактировать нельзя.", "error")
    form = await request.form()
    data, errors = validate(form, s, t)
    if errors:
        return render_form(request, s, t, data["raw"], errors, 400)
    for k, v in data["clean"].items():
        setattr(t, k, v)
    s.flush()
    s.refresh(t, ["course"])
    promoted = promote_after_limit_change(t) if t.status == "registration" else []
    for reg in promoted:
        create_invoice(s, reg)
    leaderboard.recalculate(t)
    audit.log(s, role, "update", "tournament", t.id, f"Изменены параметры турнира «{t.name}»")
    s.commit()
    msg = "Изменения сохранены."
    if promoted:
        msg += f" Из листа ожидания переведено заявок: {len(promoted)}."
    return redirect(f"/tournaments/{t.id}", msg)


@router.post("/tournaments/{tid}/status")
async def tournament_status(tid: int, request: Request, s: Session = Depends(get_session),
                            role=Depends(require("tournaments", True))):
    t = get_tournament(s, tid)
    form = await request.form()
    new = form.get("status", "")
    if new not in TRANSITIONS.get(t.status, []):
        return redirect(f"/tournaments/{t.id}", "Такой переход статуса недоступен.", "error")
    old = t.status
    extra = ""
    if new == "finished":
        confirmed = [r for r in t.registrations if r.status == "confirmed"]
        incomplete = [r for r in confirmed if r.result is None or r.result.rounds_played < t.rounds_count]
        if not confirmed or len(incomplete) == len(confirmed):
            return redirect(f"/tournaments/{t.id}?tab=results",
                            "Нельзя завершить турнир без результатов. Введите результаты раундов.", "error")
        leaderboard.recalculate(t)
        s.flush()
        affected = post_rounds_to_handicap(t)
        s.flush()
        for m in affected:
            handicap.recalculate_member(m)
        extra = f" Раунды переданы в расчёт гандикапа ({len(affected)} игроков)."
        if incomplete:
            extra += f" Без полного результата: {len(incomplete)}."
    t.status = new
    audit.log(s, role, "status", "tournament", t.id,
              f"Турнир «{t.name}»: «{TOURNAMENT_STATUS[old]}» → «{TOURNAMENT_STATUS[new]}»")
    s.commit()
    return redirect(f"/tournaments/{t.id}", f"Статус турнира: «{TOURNAMENT_STATUS[new]}».{extra}")


# ---------------------------------------------------------------- card

@router.get("/tournaments/{tid}")
def tournament_card(tid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("tournaments"))):
    t = get_tournament(s, tid)
    tab = request.query_params.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    regs = sorted(t.registrations, key=lambda r: (
        ["confirmed", "applied", "waitlist", "rejected"].index(r.status), r.applied_on, r.id))
    ctx = dict(active="tournaments", title=t.name, t=t, tab=tab, regs=regs,
               transitions=TRANSITIONS.get(t.status, []),
               counts={k: sum(1 for r in t.registrations if r.status == k) for k in REGISTRATION_STATUS})
    if tab == "registrations" and t.status == "registration":
        registered = {r.member_id for r in t.registrations}
        ctx["candidates"] = [m for m in s.scalars(
            select(Member).where(Member.status != "suspended").order_by(Member.last_name.collate("ru"), Member.first_name)
        ) if m.id not in registered]
        ctx["tees"] = [tee for tee in t.course.tees]
    if tab == "results":
        ctx["entries"] = results_entries(t)
        ctx["errors"] = {}
    if tab in ("leaderboard", "overview"):
        ctx["overall"], ctx["cat_boards"] = leaderboard.boards(t)
    return render(request, "tournaments/card.html", **ctx)


def results_entries(t: Tournament):
    entries = []
    for reg in sorted(t.registrations, key=lambda r: r.member.last_name):
        if reg.status != "confirmed":
            continue
        tee = leaderboard.tee_for(t, reg)
        ch = reg.result.course_handicap if reg.result else handicap.course_handicap(
            reg.member.handicap_index, tee.slope_rating, tee.course_rating, tee.par)
        entries.append({"reg": reg, "tee": tee, "ch": ch,
                        "scores": reg.result.scores if reg.result else [None] * 4})
    return entries


# ---------------------------------------------------------------- registrations

def create_invoice(s: Session, reg: Registration) -> None:
    t = reg.tournament
    if t.entry_fee <= 0 or reg.fee_paid:
        return
    exists = s.scalar(select(Payment.id).where(Payment.registration_id == reg.id))
    if exists:
        return
    s.add(Payment(member=reg.member, type="tournament", amount=t.entry_fee, issued_on=date.today(),
                  due_date=max(t.registration_deadline, date.today()), method="card", status="pending",
                  registration=reg, comment=f"Взнос: {t.name}"))


def drop_unpaid_invoice(s: Session, reg: Registration) -> bool:
    removed = False
    for p in s.scalars(select(Payment).where(Payment.registration_id == reg.id, Payment.status != "paid")):
        s.delete(p)
        removed = True
    return removed


@router.post("/tournaments/{tid}/register")
async def tournament_register(tid: int, request: Request, s: Session = Depends(get_session),
                              role=Depends(require("tournaments", True))):
    t = get_tournament(s, tid)
    form = await request.form()
    member_id = form.get("member_id", "")
    member = s.get(Member, int(member_id)) if member_id.isdigit() else None
    back = f"/tournaments/{t.id}?tab=registrations"
    if member is None:
        return redirect(back, "Выберите игрока.", "error")
    tee = form.get("tee") or None
    if tee and tee not in TEE_COLORS:
        return redirect(back, "Выберите ти.", "error")
    try:
        reg = register(t, member, date.today(), tee)
    except RegistrationError as exc:
        return redirect(back, str(exc), "error")
    s.flush()
    if reg.status != "waitlist":
        create_invoice(s, reg)
    audit.log(s, role, "create", "registration", reg.id,
              f"Заявка {member.full_name} на турнир «{t.name}»: «{REGISTRATION_STATUS[reg.status]}»")
    s.commit()
    if reg.status == "waitlist":
        return redirect(back, f"Лимит участников достигнут — {member.full_name} добавлен(а) в лист ожидания.", "info")
    return redirect(back, f"Заявка {member.full_name} принята.")


@router.post("/registrations/{rid}/status")
async def registration_status(rid: int, request: Request, s: Session = Depends(get_session),
                              role=Depends(require("tournaments", True))):
    reg = s.get(Registration, rid)
    if reg is None:
        raise HTTPException(404)
    form = await request.form()
    new = form.get("status", "")
    back = f"/tournaments/{reg.tournament_id}?tab=registrations"
    old = reg.status
    try:
        promoted = change_status(reg, new)
    except RegistrationError as exc:
        return redirect(back, str(exc), "error")
    notes = []
    if new in ("rejected", "waitlist"):
        if drop_unpaid_invoice(s, reg):
            notes.append("неоплаченный счёт аннулирован")
        if reg.fee_paid:
            notes.append("взнос уже оплачен — оформите возврат в бухгалтерии")
    if new in ("applied", "confirmed") and old not in ("applied", "confirmed"):
        s.flush()
        create_invoice(s, reg)
    if promoted is not None:
        s.flush()
        create_invoice(s, promoted)
        notes.append(f"из листа ожидания переведён(а) {promoted.member.full_name}")
        audit.log(s, role, "status", "registration", promoted.id,
                  f"Заявка {promoted.member.full_name} на «{reg.tournament.name}» переведена из листа ожидания")
    audit.log(s, role, "status", "registration", reg.id,
              f"Заявка {reg.member.full_name} на «{reg.tournament.name}»: "
              f"«{REGISTRATION_STATUS[old]}» → «{REGISTRATION_STATUS[reg.status]}»")
    s.commit()
    msg = f"{reg.member.full_name}: «{REGISTRATION_STATUS[reg.status]}»."
    if notes:
        text = "; ".join(notes)
        msg += " " + text[0].upper() + text[1:] + "."
    return redirect(back, msg)


@router.post("/registrations/{rid}/fee")
def registration_fee(rid: int, request: Request, s: Session = Depends(get_session),
                     role=Depends(require("tournaments", True))):
    reg = s.get(Registration, rid)
    if reg is None:
        raise HTTPException(404)
    back = f"/tournaments/{reg.tournament_id}?tab=registrations"
    if reg.fee_paid:
        return redirect(back, "Взнос уже отмечен как оплаченный.", "info")
    t = reg.tournament
    payment = s.scalar(select(Payment).where(Payment.registration_id == reg.id, Payment.status != "paid"))
    if payment is None:
        payment = Payment(member=reg.member, type="tournament", amount=t.entry_fee, issued_on=date.today(),
                          due_date=date.today(), method="card", status="pending", registration=reg,
                          comment=f"Взнос: {t.name}")
        s.add(payment)
        s.flush()
    pay.mark_paid(payment, date.today())
    reg.fee_paid = True
    audit.log(s, role, "payment", "payment", payment.id,
              f"Турнирный взнос {reg.member.full_name} («{t.name}») отмечен как оплаченный")
    s.commit()
    return redirect(back, f"Взнос {reg.member.full_name} отмечен как оплаченный ({f.fmt_money(payment.amount)}).")


# ---------------------------------------------------------------- results

@router.post("/tournaments/{tid}/results")
async def results_save(tid: int, request: Request, s: Session = Depends(get_session),
                       role=Depends(require("tournaments", True))):
    t = get_tournament(s, tid)
    if t.status != "in_progress":
        return redirect(f"/tournaments/{t.id}?tab=results",
                        "Результаты вводятся только для турнира в статусе «Идёт».", "error")
    form = await request.form()
    entries = results_entries(t)
    errors: dict[str, str] = {}
    parsed: dict[int, list] = {}
    for e in entries:
        reg = e["reg"]
        scores = []
        for k in range(1, t.rounds_count + 1):
            key = f"r{k}_{reg.id}"
            raw = (form.get(key) or "").strip()
            if not raw:
                scores.append(None)
            elif raw.isdigit() and 55 <= int(raw) <= 200:
                scores.append(int(raw))
            else:
                scores.append(raw)
                errors[key] = "Целое число 55–200"
        parsed[reg.id] = scores
    if errors:
        for e in entries:
            e["scores"] = parsed[e["reg"].id] + [None] * (4 - t.rounds_count)
        overall, cats = leaderboard.boards(t)
        regs = t.registrations
        return render(request, "tournaments/card.html", status_code=400, active="tournaments", title=t.name,
                      t=t, tab="results", entries=entries, errors=errors, regs=regs,
                      transitions=TRANSITIONS.get(t.status, []), overall=overall, cat_boards=cats,
                      counts={k: sum(1 for r in regs if r.status == k) for k in REGISTRATION_STATUS},
                      flash={"kind": "error", "text": f"Исправьте ошибки ввода: {len(errors)}."})
    changed = 0
    for e in entries:
        reg = e["reg"]
        scores = parsed[reg.id]
        if all(x is None for x in scores) and reg.result is None:
            continue
        res = leaderboard.ensure_result(t, reg)
        for k, score in enumerate(scores, start=1):
            if getattr(res, f"r{k}") != score:
                setattr(res, f"r{k}", score)
                changed += 1
    s.flush()
    leaderboard.recalculate(t)
    audit.log(s, role, "results", "tournament", t.id, f"Введены результаты турнира «{t.name}» (изменено ячеек: {changed})")
    s.commit()
    return redirect(f"/tournaments/{t.id}?tab=leaderboard", f"Результаты сохранены, позиции пересчитаны (изменено ячеек: {changed}).")


# ---------------------------------------------------------------- print

@router.get("/tournaments/{tid}/print/start")
def print_start(tid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("tournaments"))):
    t = get_tournament(s, tid)
    players = [r for r in t.registrations if r.status in ("confirmed", "applied")]
    players.sort(key=lambda r: (-(r.member.handicap_index or 54), r.member.last_name))
    groups = []
    size = 4 if len(players) > 30 else 3
    start = datetime.combine(round_date(t, 1), datetime.min.time()).replace(hour=9)
    for i in range(0, len(players), size):
        tee_time = start + timedelta(minutes=10 * (i // size))
        rows = []
        for reg in players[i:i + size]:
            tee = leaderboard.tee_for(t, reg)
            rows.append({"reg": reg, "tee": tee, "ch": reg.result.course_handicap if reg.result else
                         handicap.course_handicap(reg.member.handicap_index, tee.slope_rating, tee.course_rating, tee.par)})
        groups.append({"time": tee_time.strftime("%H:%M"), "rows": rows})
    return render(request, "print/start.html", t=t, groups=groups, round_day=round_date(t, 1))


@router.get("/tournaments/{tid}/print/final")
def print_final(tid: int, request: Request, s: Session = Depends(get_session), _=Depends(require("tournaments"))):
    t = get_tournament(s, tid)
    overall, cats = leaderboard.boards(t)
    return render(request, "print/final.html", t=t, overall=overall, cat_boards=cats)
