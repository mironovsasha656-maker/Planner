"""Russian formatting helpers, also registered as Jinja filters."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Iterable, Optional, Sequence

from app.labels import MONTHS_GENITIVE

NBSP = " "


def fmt_date(value: Optional[date]) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y")


def fmt_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


def fmt_date_long(value: Optional[date]) -> str:
    if value is None:
        return "—"
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]} {value.year}"


def fmt_int(value: Optional[int]) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", NBSP)


def fmt_money(value: Optional[int]) -> str:
    if value is None:
        return "—"
    return f"{fmt_int(value)}{NBSP}₽"


def fmt_decimal(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_signed(value: Optional[int]) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "E"
    return f"+{value}" if value > 0 else f"−{abs(value)}"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def parse_date(value: str) -> Optional[date]:
    """Accept DD.MM.YYYY (UI) and YYYY-MM-DD (HTML date input)."""
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value: str) -> Optional[float]:
    value = (value or "").strip().replace(",", ".").replace(" ", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


_PHONE_OR_NUMBER = re.compile(r"^[+-]?[\d\s()\-]+$")


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    # Neutralise spreadsheet formula injection, but keep phone numbers readable.
    if text and text[0] in "=@\t\r":
        return "'" + text
    if text and text[0] in "+-" and not _PHONE_OR_NUMBER.match(text):
        return "'" + text
    return text


def to_csv(header: Sequence[str], rows: Iterable[Sequence]) -> bytes:
    """CSV for Excel (Russian locale): UTF-8 with BOM, ';' delimiter, CRLF."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_safe(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")
