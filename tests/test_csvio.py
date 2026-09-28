import pytest

from tricount_flow.csvio import parse_amount, parse_csv


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("45", 45.0),
        ("45.00", 45.0),
        ("12,50", 12.50),  # EU decimal
        ("€1.234,56", 1234.56),  # EU thousands + decimal + symbol
        ("1,234.56", 1234.56),  # US thousands + decimal
        ("  20 ", 20.0),
        ("$99.99", 99.99),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == pytest.approx(expected)


def test_parse_amount_invalid():
    with pytest.raises(ValueError):
        parse_amount("abc")


def test_basic_comma_csv():
    text = "description,amount\nDinner,45\nTaxi,20\n"
    parsed = parse_csv(text)
    assert parsed.header_error is None
    assert len(parsed.rows) == 2
    assert parsed.rows[0].description == "Dinner"
    assert parsed.rows[0].amount == 45.0
    assert parsed.rows[0].type == "expense"


def test_semicolon_delimiter_and_split_pipe():
    text = "description;amount;split\nDinner;45;Moritz|Anna\n"
    parsed = parse_csv(text)
    assert parsed.header_error is None
    assert parsed.rows[0].split == ["Moritz", "Anna"]


def test_header_aliases_and_reimbursement():
    text = "title,cost,paid_by,type,to\nPayback,20,Moritz,reimbursement,Anna\n"
    parsed = parse_csv(text)
    row = parsed.rows[0]
    assert row.description == "Payback"
    assert row.amount == 20.0
    assert row.payer == "Moritz"
    assert row.type == "reimbursement"
    assert row.to == "Anna"


def test_missing_required_column():
    parsed = parse_csv("description,payer\nDinner,Moritz\n")
    assert parsed.header_error is not None
    assert "amount" in parsed.header_error


def test_bad_row_carries_error_but_others_ok():
    text = "description,amount\nGood,10\nBad,notanumber\n,5\n"
    parsed = parse_csv(text)
    assert parsed.rows[0].error is None
    assert "invalid amount" in parsed.rows[1].error
    assert "missing description" in parsed.rows[2].error


def test_bom_and_blank_lines():
    text = "﻿description,amount\n\nDinner,45\n\n"
    parsed = parse_csv(text)
    assert parsed.header_error is None
    assert len(parsed.rows) == 1


def test_empty_file():
    assert parse_csv("   ").header_error is not None
