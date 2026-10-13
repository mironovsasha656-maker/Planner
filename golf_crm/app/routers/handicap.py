from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models import Member
from app.services import audit, handicap
from app.web import redirect, render, require

router = APIRouter(prefix="/handicap")


def overview_rows(s: Session):
    members = s.scalars(
        select(Member).options(selectinload(Member.rounds), selectinload(Member.club))
        .order_by(Member.last_name.collate("ru"), Member.first_name.collate("ru"))
    )
    rows = []
    for m in members:
        ordered = sorted(m.rounds, key=lambda r: (r.played_on, r.id))
        calc = handicap.handicap_index([r.differential for r in ordered])
        stale = calc is not None and (m.handicap_index is None or abs(calc - m.handicap_index) > 0.05)
        rows.append({"m": m, "rounds": len(ordered), "calc": calc, "stale": stale,
                     "last": ordered[-1].played_on if ordered else None})
    return rows


@router.get("")
def handicap_page(request: Request, s: Session = Depends(get_session), _=Depends(require("handicap"))):
    rows = overview_rows(s)
    only_stale = request.query_params.get("stale") == "1"
    shown = [r for r in rows if r["stale"]] if only_stale else rows
    return render(request, "handicap/index.html", active="handicap", title="Гандикап", rows=shown,
                  total=len(rows), stale_count=sum(1 for r in rows if r["stale"]),
                  few_rounds=sum(1 for r in rows if r["rounds"] < handicap.MIN_ROUNDS), only_stale=only_stale)


@router.post("/recalc-all")
def recalc_all(request: Request, s: Session = Depends(get_session), role=Depends(require("handicap", True))):
    members = list(s.scalars(select(Member).options(selectinload(Member.rounds))))
    changed = 0
    for m in members:
        old = m.handicap_index
        new = handicap.recalculate_member(m)
        if new is not None and old != new:
            changed += 1
    audit.log(s, role, "handicap", "member", None,
              f"Массовый пересчёт гандикапа: обработано {len(members)} игроков, изменён индекс у {changed}")
    s.commit()
    return redirect("/handicap", f"Пересчёт выполнен: обработано игроков — {len(members)}, индекс изменился у {changed}.")
