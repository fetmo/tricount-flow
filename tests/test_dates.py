from datetime import date

import pytest

from tricount_flow.core import CoreError, parse_date


def test_none_and_empty():
    assert parse_date(None) is None
    assert parse_date("   ") is None


def test_iso():
    dt = parse_date("2026-09-25")
    assert (dt.year, dt.month, dt.day) == (2026, 9, 25)
    assert dt.hour == 12  # noon, to avoid TZ day-shift


def test_european_day_first():
    dt = parse_date("25.09.2026")
    assert (dt.year, dt.month, dt.day) == (2026, 9, 25)


def test_day_month_defaults_current_year():
    dt = parse_date("25.09")
    assert (dt.month, dt.day) == (9, 25)
    assert dt.year == date.today().year


def test_slash_form():
    dt = parse_date("25/09/2026")
    assert (dt.year, dt.month, dt.day) == (2026, 9, 25)


def test_invalid_raises():
    with pytest.raises(CoreError):
        parse_date("not-a-date")
