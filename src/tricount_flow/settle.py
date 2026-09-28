"""Greedy debt netting: turn per-member balances into a short list of payments.

Input is ``{member_name: net_balance}`` where a positive balance means the member
is *owed* money (creditor) and a negative balance means they *owe* (debtor) —
this matches ``tricount-api``'s ``get_balances()``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Payment:
    frm: str  # debtor
    to: str  # creditor
    amount: float


def settle(balances: dict[str, float], eps: float = 0.01) -> list[Payment]:
    """Return a near-minimal list of payments that zero out the balances."""
    creditors = sorted(
        ([n, b] for n, b in balances.items() if b > eps),
        key=lambda x: x[1],
        reverse=True,
    )
    debtors = sorted(
        ([n, -b] for n, b in balances.items() if b < -eps),
        key=lambda x: x[1],
        reverse=True,
    )

    payments: list[Payment] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor, creditor = debtors[i], creditors[j]
        amount = round(min(debtor[1], creditor[1]), 2)
        if amount > 0:
            payments.append(Payment(frm=debtor[0], to=creditor[0], amount=amount))
        debtor[1] -= amount
        creditor[1] -= amount
        if debtor[1] <= eps:
            i += 1
        if creditor[1] <= eps:
            j += 1
    return payments
