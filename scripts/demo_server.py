"""Run the real web UI with sample data, for docs screenshots.

This wires the actual FastAPI app / templates / CSS to a fake in-memory core so we
can capture a realistic screenshot without a live tricount. The data is obviously
fictional demo data — nothing here talks to Tricount.

    uv run python scripts/demo_server.py --port 8790
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import uvicorn

from tricount_flow.core import BalanceReport, ExpenseRow
from tricount_flow.settle import settle
from tricount_flow.web.app import create_app

MEMBERS = ["Moritz", "Anna", "Ben", "Chloé"]
CURRENCY = "EUR"
BALANCES = {"Moritz": 84.20, "Anna": 12.50, "Ben": -46.30, "Chloé": -50.40}
EXPENSES = [
    ExpenseRow("2026-09-27", "Ski passes", "Moritz", 240.00, CURRENCY, "TRANSPORT", "NORMAL"),
    ExpenseRow(
        "2026-09-26", "Chalet (2 nights)", "Anna", 600.00, CURRENCY, "RENT_AND_UTILITIES", "NORMAL"
    ),
    ExpenseRow("2026-09-26", "Groceries", "Ben", 78.40, CURRENCY, "GROCERIES", "NORMAL"),
    ExpenseRow(
        "2026-09-25", "Fondue dinner", "Moritz", 96.00, CURRENCY, "FOOD_AND_DRINK", "NORMAL"
    ),
    ExpenseRow(
        "2026-09-25", "Payback to Anna", "Chloé", 40.00, CURRENCY, "Reimbursement", "BALANCE"
    ),
]


class _FakeCore:
    cfg = SimpleNamespace(tricounts={"ski-trip": None, "household": None}, default="ski-trip")

    def info(self, name):
        return {
            "name": name or "ski-trip",
            "title": "Ski Trip 2026 (demo)",
            "currency": CURRENCY,
            "members": MEMBERS,
            "me": "Moritz",
        }

    def balances(self, name):
        return BalanceReport(
            tricount=name or "ski-trip",
            title="Ski Trip 2026 (demo)",
            currency=CURRENCY,
            balances=dict(BALANCES),
            settlements=settle(BALANCES),
        )

    def list_expenses(self, name, limit=10):
        return EXPENSES[:limit]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(create_app(_FakeCore()), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
