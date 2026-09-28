from tricount_flow.settle import Payment, settle


def _total_moved(payments):
    return round(sum(p.amount for p in payments), 2)


def test_empty_when_balanced():
    assert settle({"A": 0.0, "B": 0.0}) == []


def test_simple_two_person():
    # A is owed 10, B owes 10 -> B pays A 10
    assert settle({"A": 10.0, "B": -10.0}) == [Payment(frm="B", to="A", amount=10.0)]


def test_three_way_minimises_transfers():
    # A paid for everyone: A +20, B -10, C -10 -> two payments to A
    payments = settle({"A": 20.0, "B": -10.0, "C": -10.0})
    assert len(payments) == 2
    assert {p.frm for p in payments} == {"B", "C"}
    assert all(p.to == "A" for p in payments)
    assert _total_moved(payments) == 20.0


def test_amounts_conserved():
    balances = {"A": 15.0, "B": 5.0, "C": -12.0, "D": -8.0}
    payments = settle(balances)
    assert _total_moved(payments) == 20.0
    # everyone who owes appears as a debtor, everyone owed as a creditor
    assert {p.frm for p in payments} <= {"C", "D"}
    assert {p.to for p in payments} <= {"A", "B"}


def test_ignores_sub_cent_noise():
    assert settle({"A": 0.004, "B": -0.004}) == []
