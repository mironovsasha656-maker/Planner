from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Club, Member, Tournament, Course
from app.web import render, require

router = APIRouter(prefix="/clubs")


@router.get("")
def clubs_list(request: Request, s: Session = Depends(get_session), _=Depends(require("clubs"))):
    rows = s.execute(
        select(Club, func.count(Member.id))
        .outerjoin(Member, Member.club_id == Club.id)
        .group_by(Club.id)
        .order_by(Club.name)
    ).all()
    return render(request, "clubs/list.html", active="clubs", title="Клубы и поля", rows=rows)


@router.get("/{club_id}")
def club_card(club_id: int, request: Request, s: Session = Depends(get_session), _=Depends(require("clubs"))):
    club = s.get(Club, club_id)
    if club is None:
        raise HTTPException(404)
    members = list(s.scalars(
        select(Member).where(Member.club_id == club.id).order_by(Member.last_name.collate("ru"), Member.first_name)
    ))
    tournaments = list(s.scalars(
        select(Tournament).join(Course).where(Course.club_id == club.id).order_by(Tournament.start_date.desc())
    ))
    indexes = [m.handicap_index for m in members if m.handicap_index is not None]
    return render(request, "clubs/card.html", active="clubs", title=club.name, club=club, members=members,
                  tournaments=tournaments,
                  avg_hcp=sum(indexes) / len(indexes) if indexes else None,
                  active_count=sum(1 for m in members if m.status == "active"))
