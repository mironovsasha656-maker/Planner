"""Start the demo: creates and seeds golf_crm.db on first run, then opens the browser.

    python run.py              start (seed only if the database does not exist)
    python run.py --reset      recreate the database with fresh demo data
    python run.py --no-browser do not open the browser automatically
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

if sys.version_info < (3, 11):
    sys.exit("Нужен Python 3.11 или новее.")

import uvicorn  # noqa: E402

from app import config  # noqa: E402


def prepare_database(reset: bool) -> None:
    import seed
    from app.db import SessionLocal, create_all

    if reset or not config.DB_PATH.exists():
        print("Создаю базу данных и демо-данные…")
        seed.reset_database()
        with SessionLocal() as session:
            seed.seed(session)
        print(f"Готово: {config.DB_PATH}")
    else:
        create_all()


def main() -> None:
    parser = argparse.ArgumentParser(description="CRM Федерации гольфа МО (демо)")
    parser.add_argument("--reset", action="store_true", help="пересоздать базу с демо-данными")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()

    prepare_database(args.reset)
    url = f"http://localhost:{args.port}"
    print(f"Открываю {url} (остановить: Ctrl+C)")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=config.HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
