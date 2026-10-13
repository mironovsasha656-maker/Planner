"""Database engine and session factory (SQLite, single file)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


def _ru_key(value):
    return (value or "").lower().replace("ё", "е")


def _install_sqlite_functions(dbapi_conn, _record):
    # SQLite LOWER()/LIKE only fold ASCII; register Unicode-aware helpers for Cyrillic.
    dbapi_conn.create_function("py_lower", 1, lambda s: _ru_key(s) if s is not None else None)
    dbapi_conn.create_collation(
        "ru", lambda a, b: (_ru_key(a) > _ru_key(b)) - (_ru_key(a) < _ru_key(b))
    )
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _install_sqlite_functions)
    return engine


engine = make_engine(f"sqlite:///{config.DB_PATH}")
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_all(bind=None):
    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind or engine)
