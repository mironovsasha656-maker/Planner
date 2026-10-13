from datetime import date

from app.services import formatting as f


def test_money_and_numbers_use_russian_format():
    assert f.fmt_money(5000) == "5 000 ₽"
    assert f.fmt_money(2365000) == "2 365 000 ₽"
    assert f.fmt_decimal(18.4) == "18,4"
    assert f.fmt_signed(-3) == "−3" and f.fmt_signed(0) == "E" and f.fmt_signed(4) == "+4"


def test_dates():
    assert f.fmt_date(date(2026, 9, 5)) == "05.09.2026"
    assert f.parse_date("05.09.2026") == date(2026, 9, 5)
    assert f.parse_date("2026-09-05") == date(2026, 9, 5)
    assert f.parse_date("31.02.2026") is None
    assert f.fmt_date_long(date(2026, 9, 30)) == "30 сентября 2026"


def test_plural():
    assert [f.plural(n, "игрок", "игрока", "игроков") for n in (1, 3, 5, 11, 21, 104)] == [
        "игрок", "игрока", "игроков", "игроков", "игрок", "игрока"]


def test_csv_for_excel():
    data = f.to_csv(["ФИО", "Телефон", "Заметка"], [["Иванов И.И.", "+7 (916) 123-45-67", "=СУММ(A1)"]])
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert text.splitlines() == ["ФИО;Телефон;Заметка", "Иванов И.И.;+7 (916) 123-45-67;'=СУММ(A1)"]
