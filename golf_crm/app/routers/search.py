from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Club, Member, Tournament
from app.web import can, render

router = APIRouter(prefix="/search")


def run_search(s: Session, request: Request, q: str, limit: int):
    q = q.strip()[:100]
    results = {"players": [], "clubs": [], "tournaments": []}
    if len(q) < 2:
        return q, results
    needle = q.lower().replace("ё", "е")
    if can(request, "players"):
        results["players"] = list(s.scalars(
            select(Member).where(
                func.py_lower(Member.last_name + " " + Member.first_name + " " + Member.middle_name).contains(needle)
                | func.py_lower(Member.license_number).contains(needle)
                | func.py_lower(Member.email).contains(needle)
            ).order_by(Member.last_name.collate("ru")).limit(limit)
        ))
    if can(request, "clubs"):
        results["clubs"] = list(s.scalars(
            select(Club).where(func.py_lower(Club.name).contains(needle) | func.py_lower(Club.district).contains(needle))
            .order_by(Club.name).limit(limit)
        ))
    if can(request, "tournaments"):
        results["tournaments"] = list(s.scalars(
            select(Tournament).where(func.py_lower(Tournament.name).contains(needle))
            .order_by(Tournament.start_date.desc()).limit(limit)
        ))
    return q, results


@router.get("/quick")
def quick(request: Request, q: str = "", s: Session = Depends(get_session)):
    q, results = run_search(s, request, q, 6)
    return render(request, "search/_quick.html", q=q, results=results)


@router.get("")
def full(request: Request, q: str = "", s: Session = Depends(get_session)):
    q, results = run_search(s, request, q, 50)
    return render(request, "search/results.html", title="Поиск", q=q, results=results)
