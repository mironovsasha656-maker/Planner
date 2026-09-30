"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.db import SessionLocal, create_all
from app.routers import (
    audit,
    clubs,
    dashboard,
    finance,
    handicap,
    mailings,
    officials,
    players,
    roles,
    search,
    tournaments,
)
from app.services import payments
from app.web import render

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_all()
    with SessionLocal() as session:
        if payments.refresh_overdue(session, date.today()):
            session.commit()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ФГМО CRM (демо)", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > config.MAX_FORM_BYTES:
            return PlainTextResponse("Слишком большой объём данных формы.", status_code=413)
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        messages = {
            403: ("Недостаточно прав", "Этот раздел или действие недоступно для выбранной демо-роли. "
                                      "Переключите роль в верхней панели."),
            404: ("Страница не найдена", "Запрошенная запись не существует или была удалена."),
        }
        title, text = messages.get(exc.status_code, ("Ошибка", "Не удалось выполнить запрос."))
        return render(request, "error.html", status_code=exc.status_code, title=title, text=text,
                      code=exc.status_code)

    for module in (dashboard, players, clubs, tournaments, handicap, finance, officials, mailings, audit,
                   search, roles):
        app.include_router(module.router)

    return app


app = create_app()
