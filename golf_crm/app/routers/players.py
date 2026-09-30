from __future__ import annotations

import math
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import config
from app.db import get_session
from app.labels import AGE_CATEGORY, GENDER, MEMBER_STATUS, TEE_COLORS
from app.models import Club, Course, CourseTee, Member, Payment, Round
from app.services import audit, handicap
from app.services import formatting as f
from app.services.payments import membership_fee
from app.web import redirect, render, require
from app import timeutil as msk

router = APIRouter(prefix="/players")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[+\d][\d\s()\-]{6,20}$")

# sort key -> (column, inverted); "age" ascending means the latest birth date first.
SORTS = {
    "name": (Member.last_name.collate("ru"), False),
    "club": (Club.name.collate("ru"), False),
    "hcp": (Member.handicap_index, False),
    "age": (Member.birth_date, True),
    "join": (Member.join_date, False),
    "status": (Member.status, False),
    "license": (Member.license_number, False),
}


def years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 February
        return today.replace(year=today.year - years, day=28)


def read_filters(request: Request) -> dict:
    q = request.query_params
    return {
        "q": (q.get("q") or "").strip()[:100],
        "club": q.get("club") or "",
        "status": q.get("status") or "",
        "age": q.get("age") or "",
        "hcp_min": (q.get("hcp_min") or "").strip()[:6],
        "hcp_max": (q.get("hcp_max") or "").strip()[:6],
        "sort": q.get("sort") or "name",
    }


def filtered_query(params: dict, today: date):
    stmt = select(Member).outerjoin(Club, Member.club_id == Club.id).options(selectinload(Member.club))
    if params["q"]:
        needle = params["q"].lower().replace("ё", "е")
        stmt = stmt.where(
            func.py_lower(Member.last_name + " " + Member.first_name + " " + Member.middle_name).contains(needle)
            | func.py_lower(Member.email).contains(needle)
            | Member.phone.contains(params["q"])
            | func.py_lower(Member.license_number).contains(needle)
        )
    if params["club"].isdigit():
        stmt = stmt.where(Member.club_id == int(params["club"]))
    if params["status"] in MEMBER_STATUS:
        stmt = stmt.where(Member.status == params["status"])
    if params["age"] == "junior":
        stmt = stmt.where(Member.birth_date > years_ago(today, config.JUNIOR_MAX_AGE + 1))
    elif params["age"] == "senior":
        stmt = stmt.where(Member.birth_date <= years_ago(today, config.SENIOR_MIN_AGE))
    elif params["age"] == "adult":
        stmt = stmt.where(
            Member.birth_date <= years_ago(today, config.JUNIOR_MAX_AGE + 1),
            Member.birth_date > years_ago(today, config.SENIOR_MIN_AGE),
        )
    lo, hi = f.parse_decimal(params["hcp_min"]), f.parse_decimal(params["hcp_max"])
    if lo is not None:
        stmt = stmt.where(Member.handicap_index >= lo)
    if hi is not None:
        stmt = stmt.where(Member.handicap_index <= hi)
    key = params["sort"].lstrip("-")
    column, inverted = SORTS.get(key, SORTS["name"])
    descending = params["sort"].startswith("-") != inverted
    primary = column.desc() if descending else column.asc()
    return stmt.order_by(primary, Member.last_name.collate("ru"), Member.first_name.collate("ru"), Member.id)


@router.get("")
def players_list(request: Request, s: Session = Depends(get_session), _=Depends(require("players"))):
    today = msk.today()
    params = read_filters(request)
    stmt = filtered_query(params, today)
    total = s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    pages = max(1, math.ceil(total / config.PAGE_SIZE))
    page = request.query_params.get("page", "1")
    page = min(max(int(page) if page.isdigit() else 1, 1), pages)
    members = list(s.scalars(stmt.offset((page - 1) * config.PAGE_SIZE).limit(config.PAGE_SIZE)))
    clubs = list(s.scalars(select(Club).order_by(Club.name)))
    ctx = dict(active="players", title="Игроки", members=members, total=total, page=page, pages=pages,
               params=params, clubs=clubs)
    if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == "results":
        return render(request, "players/_table.html", **ctx)
    return render(request, "players/list.html", **ctx)


@router.get("/export.csv")
def players_export(request: Request, s: Session = Depends(get_session), role=Depends(require("players"))):
    params = read_filters(request)
    members = list(s.scalars(filtered_query(params, msk.today())))
    rows = [
        (
            m.license_number, m.full_name, f.fmt_date(m.birth_date), GENDER[m.gender],
            AGE_CATEGORY[m.age_category], m.club.name if m.club else "", m.city, m.phone, m.email,
            MEMBER_STATUS[m.status], f.fmt_date(m.join_date), f.fmt_decimal(m.handicap_index),
            "да" if m.pd_consent else "нет",
        )
        for m in members
    ]
    data = f.to_csv(
        ["Лицензия", "ФИО", "Дата рождения", "Пол", "Возрастная категория", "Клуб", "Город", "Телефон",
         "E-mail", "Статус", "Дата вступления", "Индекс гандикапа", "Согласие на обработку ПДн"],
        rows,
    )
    audit.log(s, role, "export", "member", None, f"Экспорт списка игроков в CSV ({len(rows)} записей)")
    s.commit()
    filename = f"players_{msk.today():%Y%m%d}.csv"
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------- create / edit

FIELDS = ("last_name", "first_name", "middle_name", "birth_date", "gender", "phone", "email", "city",
          "club_id", "status", "join_date", "handicap_index", "notes", "pd_consent")


def validate(form, s: Session, today: date) -> tuple[dict, dict]:
    data = {k: (form.get(k) or "").strip() for k in FIELDS}
    data["pd_consent"] = form.get("pd_consent") == "on"
    errors: dict[str, str] = {}
    limits = {"last_name": 60, "first_name": 60, "middle_name": 60, "city": 80, "email": 120, "phone": 30,
              "notes": 2000}
    for key, limit in limits.items():
        if len(data[key]) > limit:
            errors[key] = f"Не более {limit} символов."
    for key, label in (("last_name", "фамилию"), ("first_name", "имя")):
        if not data[key]:
            errors[key] = f"Укажите {label}."
    birth = f.parse_date(data["birth_date"])
    if not data["birth_date"]:
        errors["birth_date"] = "Укажите дату рождения."
    elif birth is None:
        errors["birth_date"] = "Дата должна быть в формате ДД.ММ.ГГГГ."
    elif birth > today - timedelta(days=5 * 365):
        errors["birth_date"] = "Игроку должно быть не меньше 5 лет."
    elif birth < date(1920, 1, 1):
        errors["birth_date"] = "Проверьте год рождения."
    if data["gender"] not in GENDER:
        errors["gender"] = "Выберите пол."
    if data["phone"] and not PHONE_RE.match(data["phone"]):
        errors["phone"] = "Телефон: цифры, пробелы, скобки и дефисы, например +7 (916) 123-45-67."
    if data["email"] and not EMAIL_RE.match(data["email"]):
        errors["email"] = "Введите корректный адрес электронной почты."
    club_id = int(data["club_id"]) if data["club_id"].isdigit() else None
    if data["club_id"] and (club_id is None or s.get(Club, club_id) is None):
        errors["club_id"] = "Выберите клуб из списка."
    if data["status"] not in MEMBER_STATUS:
        errors["status"] = "Выберите статус."
    join = f.parse_date(data["join_date"])
    if not data["join_date"]:
        errors["join_date"] = "Укажите дату вступления."
    elif join is None:
        errors["join_date"] = "Дата должна быть в формате ДД.ММ.ГГГГ."
    elif join > today:
        errors["join_date"] = "Дата вступления не может быть в будущем."
    elif birth and join < birth:
        errors["join_date"] = "Дата вступления раньше даты рождения."
    hcp = f.parse_decimal(data["handicap_index"])
    if data["handicap_index"] and hcp is None:
        errors["handicap_index"] = "Введите число, например 18,4."
    elif hcp is not None and not 0 <= hcp <= 54:
        errors["handicap_index"] = "Индекс гандикапа должен быть от 0,0 до 54,0."
    clean = dict(data, birth_date=birth, join_date=join, club_id=club_id,
                 handicap_index=handicap.round1(hcp) if hcp is not None else None)
    return clean, errors


def form_values(m: Member | None) -> dict:
    if m is None:
        return {"gender": "M", "status": "active", "join_date": f.fmt_date(msk.today()), "pd_consent": True}
    return {
        "last_name": m.last_name, "first_name": m.first_name, "middle_name": m.middle_name,
        "birth_date": f.fmt_date(m.birth_date), "gender": m.gender, "phone": m.phone, "email": m.email,
        "city": m.city, "club_id": str(m.club_id or ""), "status": m.status,
        "join_date": f.fmt_date(m.join_date),
        "handicap_index": f.fmt_decimal(m.handicap_index) if m.handicap_index is not None else "",
        "notes": m.notes, "pd_consent": m.pd_consent,
    }


def next_license(s: Session, year: int) -> str:
    prefix = f"MO-{year}-"
    last = s.scalar(select(func.max(Member.license_number)).where(Member.license_number.like(prefix + "%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def render_form(request, s, member, values, errors, status_code=200):
    clubs = list(s.scalars(select(Club).order_by(Club.name)))
    return render(request, "players/form.html", status_code=status_code, active="players",
                  title="Редактирование игрока" if member else "Новый игрок",
                  member=member, v=values, errors=errors, clubs=clubs)


@router.get("/new")
def player_new(request: Request, s: Session = Depends(get_session), _=Depends(require("players", True))):
    return render_form(request, s, None, form_values(None), {})


@router.post("/new")
async def player_create(request: Request, s: Session = Depends(get_session), role=Depends(require("players", True))):
    form = await request.form()
    today = msk.today()
    data, errors = validate(form, s, today)
    if data["email"] and s.scalar(select(Member.id).where(func.py_lower(Member.email) == data["email"].lower())):
        errors["email"] = "Игрок с таким e-mail уже есть в реестре."
    if errors:
        return render_form(request, s, None, dict(form, pd_consent=data["pd_consent"]), errors, 400)
    m = Member(**{k: data[k] for k in FIELDS}, license_number=next_license(s, today.year))
    s.add(m)
    s.flush()
    fee = membership_fee(m, today)
    s.add(Payment(member=m, type="membership", amount=fee, issued_on=today,
                  due_date=today + timedelta(days=config.MEMBERSHIP_PAYMENT_TERM_DAYS), method="invoice",
                  status="pending", period_year=today.year, comment=f"Членский взнос за {today.year} год"))
    audit.log(s, role, "create", "member", m.id, f"Добавлен игрок {m.full_name} ({m.license_number})")
    s.commit()
    return redirect(f"/players/{m.id}",
                    f"Игрок добавлен, лицензия {m.license_number}. Выставлен счёт на членский взнос {f.fmt_money(fee)}.")


def get_member(s: Session, member_id: int) -> Member:
    m = s.get(Member, member_id)
    if m is None:
        raise HTTPException(404)
    return m


@router.get("/{member_id}/edit")
def player_edit(member_id: int, request: Request, s: Session = Depends(get_session),
                _=Depends(require("players", True))):
    m = get_member(s, member_id)
    return render_form(request, s, m, form_values(m), {})


@router.post("/{member_id}/edit")
async def player_update(member_id: int, request: Request, s: Session = Depends(get_session),
                        role=Depends(require("players", True))):
    m = get_member(s, member_id)
    form = await request.form()
    data, errors = validate(form, s, msk.today())
    if data["email"] and s.scalar(select(Member.id).where(
            func.py_lower(Member.email) == data["email"].lower(), Member.id != m.id)):
        errors["email"] = "Игрок с таким e-mail уже есть в реестре."
    if errors:
        return render_form(request, s, m, dict(form, pd_consent=data["pd_consent"]), errors, 400)
    changed = [k for k in FIELDS if getattr(m, k) != data[k]]
    for k in FIELDS:
        setattr(m, k, data[k])
    if changed:
        audit.log(s, role, "update", "member", m.id, f"Изменены данные игрока {m.full_name}: {', '.join(changed)}")
    s.commit()
    return redirect(f"/players/{m.id}", "Изменения сохранены." if changed else "Изменений нет.")


@router.post("/{member_id}/status")
async def player_status(member_id: int, request: Request, s: Session = Depends(get_session),
                        role=Depends(require("players", True))):
    m = get_member(s, member_id)
    form = await request.form()
    new = form.get("status", "")
    if new not in MEMBER_STATUS:
        return redirect(f"/players/{m.id}", "Неизвестный статус.", "error")
    old = m.status
    m.status = new
    audit.log(s, role, "status", "member", m.id,
              f"Статус игрока {m.full_name}: «{MEMBER_STATUS[old]}» → «{MEMBER_STATUS[new]}»")
    s.commit()
    return redirect(f"/players/{m.id}", f"Статус изменён на «{MEMBER_STATUS[new]}».")


# ---------------------------------------------------------------- card

@router.get("/{member_id}")
def player_card(member_id: int, request: Request, s: Session = Depends(get_session), _=Depends(require("players"))):
    m = get_member(s, member_id)
    tab = request.query_params.get("tab", "profile")
    if tab not in ("profile", "handicap", "tournaments", "payments"):
        tab = "profile"
    rounds = sorted(m.rounds, key=lambda r: (r.played_on, r.id))
    diffs = [r.differential for r in rounds]
    counted = handicap.counted_positions(diffs)
    window_start = max(0, len(rounds) - handicap.WINDOW)
    history = handicap.index_history([(r.played_on, r.differential) for r in rounds])
    calc_index = handicap.handicap_index(diffs)
    rule = handicap.rule_for(len(rounds) - window_start)
    table = [
        {"round": r, "counted": i in counted, "in_window": i >= window_start}
        for i, r in enumerate(rounds)
    ]
    table.reverse()
    tees = list(s.execute(
        select(CourseTee, Course, Club).join(Course, CourseTee.course_id == Course.id)
        .join(Club, Course.club_id == Club.id).order_by(Club.name, Course.id, CourseTee.id)
    ))
    registrations = sorted(m.registrations, key=lambda r: r.tournament.start_date, reverse=True)
    chart = {
        "labels": [f.fmt_date(p.played_on) for p in history],
        "index": [p.index for p in history],
        "diffs": diffs,
    }
    return render(request, "players/card.html", active="players", title=m.full_name, m=m, tab=tab,
                  table=table, rule=rule, calc_index=calc_index, chart=chart, tees=tees,
                  registrations=registrations, TEE_COLORS=TEE_COLORS, window=handicap.WINDOW,
                  unpaid_total=sum(p.amount for p in m.payments if p.status != "paid"))


@router.post("/{member_id}/recalc")
def player_recalc(member_id: int, request: Request, s: Session = Depends(get_session),
                  role=Depends(require("handicap", True))):
    m = get_member(s, member_id)
    old = m.handicap_index
    new = handicap.recalculate_member(m)
    if new is None:
        return redirect(f"/players/{m.id}?tab=handicap",
                        "Для расчёта нужно минимум 3 раунда. Индекс не изменён.", "error")
    audit.log(s, role, "handicap", "member", m.id,
              f"Пересчитан гандикап игрока {m.full_name}: {f.fmt_decimal(old)} → {f.fmt_decimal(new)}")
    s.commit()
    return redirect(f"/players/{m.id}?tab=handicap",
                    f"Гандикап пересчитан: {f.fmt_decimal(old)} → {f.fmt_decimal(new)}.")


@router.post("/{member_id}/rounds")
async def player_add_round(member_id: int, request: Request, s: Session = Depends(get_session),
                           role=Depends(require("handicap", True))):
    m = get_member(s, member_id)
    form = await request.form()
    played = f.parse_date(form.get("played_on", ""))
    tee_id = form.get("tee_id", "")
    score = (form.get("score") or "").strip()
    tee = s.get(CourseTee, int(tee_id)) if tee_id.isdigit() else None
    error = None
    if played is None:
        error = "Укажите дату раунда."
    elif played > msk.today():
        error = "Дата раунда не может быть в будущем."
    elif tee is None:
        error = "Выберите поле и ти."
    elif not score.isdigit() or not 55 <= int(score) <= 200:
        error = "Результат раунда (гросс) должен быть целым числом от 55 до 200."
    if error:
        return redirect(f"/players/{m.id}?tab=handicap", error, "error")
    diff = handicap.score_differential(int(score), tee.course_rating, tee.slope_rating)
    m.rounds.append(Round(tee=tee, played_on=played, adjusted_gross=int(score), differential=diff))
    s.flush()
    audit.log(s, role, "create", "round", m.id,
              f"Добавлен раунд игроку {m.full_name}: {score} ударов, дифференциал {f.fmt_decimal(diff)}")
    s.commit()
    return redirect(f"/players/{m.id}?tab=handicap",
                    f"Раунд добавлен, дифференциал {f.fmt_decimal(diff)}. Нажмите «Пересчитать гандикап», "
                    "чтобы обновить индекс.")
