"""Lenient CSV parsing for bulk expense import.

Accepts a friendly, forgiving schema so exports from spreadsheets "just work":

    description, amount, payer, split, category, date, type, to

- Headers are case-insensitive and accept common aliases (incl. a few DE/FR terms).
- Only ``description`` and ``amount`` are required; everything else has a default.
- Delimiter (``,`` ``;`` ``tab``) is auto-detected; amounts accept EU or US decimals
  and currency symbols (``12,50``, ``€1.234,56``, ``1,234.56``).
- ``split`` lists members separated by ``|`` (or ``,``/``;`` when that isn't the CSV
  delimiter).
- ``type`` defaults to ``expense``; ``reimbursement``/``payment``/``transfer`` mark a
  payback (which then needs a ``to`` member).

Parsing never raises on bad *rows*: each row carries an ``error`` if it couldn't be
understood, so the importer can report a per-row summary. A structural problem
(missing required column) is returned as ``header_error``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

_HEADER_ALIASES = {
    "description": {"description", "desc", "title", "name", "what", "label", "memo", "item"},
    "amount": {"amount", "cost", "price", "total", "sum", "value", "betrag", "montant"},
    "payer": {"payer", "paid_by", "paidby", "paid by", "who", "wer", "from"},
    "split": {
        "split",
        "split_among",
        "among",
        "participants",
        "for",
        "with",
        "beteiligte",
        "shared_with",
    },
    "category": {"category", "cat", "kategorie", "categorie", "catégorie", "type_category"},
    "date": {"date", "when", "day", "datum", "date_occurred"},
    "type": {"type", "kind", "art", "entry_type"},
    "to": {"to", "receiver", "recipient", "empfaenger", "empfänger", "beneficiary"},
}

_REIMBURSEMENT_WORDS = {
    "reimbursement",
    "reimburse",
    "payment",
    "payback",
    "transfer",
    "settle",
    "balance",
}


@dataclass
class ImportRow:
    line: int  # 1-based data row (header is line 0)
    description: str
    amount: float | None
    payer: str | None
    split: list[str] | None
    category: str | None
    date: str | None
    type: str  # "expense" | "reimbursement"
    to: str | None
    error: str | None = None


@dataclass
class ParsedCsv:
    rows: list[ImportRow]
    header_error: str | None = None


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        # Fall back to whichever common delimiter appears most on the first line.
        first = sample.splitlines()[0] if sample.splitlines() else ""
        return max(",;\t", key=first.count) if first else ","


def parse_amount(raw: str) -> float:
    """Parse an amount string with EU/US decimals and currency symbols."""
    s = re.sub(r"[^0-9.,-]", "", (raw or "").strip())
    if not s:
        raise ValueError("empty amount")
    if "." in s and "," in s:
        # The right-most separator is the decimal point; the other is thousands.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Single comma -> decimal; multiple commas -> thousands separators.
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    return float(s)


def _split_members(raw: str, delimiter: str) -> list[str]:
    seps = {"|"} | ({",", ";"} - {delimiter})
    pattern = "[" + re.escape("".join(seps)) + "]"
    return [p.strip() for p in re.split(pattern, raw) if p.strip()]


def parse_csv(text: str) -> ParsedCsv:
    text = text.lstrip("﻿")  # strip BOM
    if not text.strip():
        return ParsedCsv(rows=[], header_error="The file is empty.")

    delimiter = _detect_delimiter("\n".join(text.splitlines()[:5]))
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    records = [r for r in reader if any(cell.strip() for cell in r)]
    if not records:
        return ParsedCsv(rows=[], header_error="The file has no data.")

    header = [h.strip().lower() for h in records[0]]
    colmap: dict[str, int] = {}
    for idx, name in enumerate(header):
        for canonical, aliases in _HEADER_ALIASES.items():
            if name in aliases and canonical not in colmap:
                colmap[canonical] = idx

    for required in ("description", "amount"):
        if required not in colmap:
            return ParsedCsv(
                rows=[],
                header_error=(
                    f"Missing required column '{required}'. "
                    f"Found columns: {', '.join(header) or '(none)'}."
                ),
            )

    def cell(row: list[str], key: str) -> str:
        idx = colmap.get(key)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    rows: list[ImportRow] = []
    for i, record in enumerate(records[1:], start=1):
        description = cell(record, "description")
        amount_raw = cell(record, "amount")
        raw_type = cell(record, "type").lower()
        row_type = "reimbursement" if raw_type in _REIMBURSEMENT_WORDS else "expense"
        split_raw = cell(record, "split")

        error: str | None = None
        amount: float | None = None
        if not description:
            error = "missing description"
        else:
            try:
                amount = parse_amount(amount_raw)
            except ValueError:
                error = f"invalid amount '{amount_raw}'"
            else:
                if amount <= 0:
                    error = f"amount must be positive (got {amount})"

        rows.append(
            ImportRow(
                line=i,
                description=description,
                amount=amount,
                payer=cell(record, "payer") or None,
                split=_split_members(split_raw, delimiter) or None,
                category=cell(record, "category") or None,
                date=cell(record, "date") or None,
                type=row_type,
                to=cell(record, "to") or None,
                error=error,
            )
        )
    return ParsedCsv(rows=rows)
