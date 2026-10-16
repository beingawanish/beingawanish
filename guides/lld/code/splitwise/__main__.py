"""Runnable slice: one trip, four split kinds, two currencies, simplified settle-up.

Run with: python3 -m splitwise
"""

import logging
from datetime import UTC, datetime

from . import (
    JPY,
    USD,
    EqualSplit,
    ExactSplit,
    ExpenseService,
    FixedClock,
    InvalidSplitError,
    Money,
    OverpaymentError,
    PercentSplit,
    SequentialIds,
    SharesSplit,
)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    svc = ExpenseService(
        clock=FixedClock(datetime(2026, 10, 16, 19, 30, tzinfo=UTC)), ids=SequentialIds()
    )
    for user_id, name in [("awanish", "Awanish"), ("bea", "Bea"), ("chen", "Chen"), ("dev", "Dev")]:
        svc.register_user(user_id, name)
    trip = svc.create_group("Goa trip", "awanish", ["bea", "chen", "dev"]).group_id

    dinner = svc.add_expense(
        trip, "awanish", Money.of("100.00", USD), EqualSplit(["awanish", "bea", "chen"]), "Dinner"
    )
    print("dinner shares:", {u: str(m) for u, m in dinner.shares})
    svc.add_expense(
        trip,
        "bea",
        Money.of("300.00", USD),
        ExactSplit(
            {
                "awanish": Money.of("120.00", USD),
                "bea": Money.of("90.00", USD),
                "dev": Money.of("90.00", USD),
            }
        ),
        "Hotel",
    )
    svc.add_expense(
        trip,
        "chen",
        Money.of("45.00", USD),
        PercentSplit({"awanish": "50", "chen": "30", "dev": "20"}),
        "Taxi",
    )
    svc.add_expense(
        trip,
        "dev",
        Money.of("80.00", USD),
        SharesSplit({"awanish": 1, "bea": 2, "chen": 1, "dev": 1}),
        "Groceries",
    )
    svc.add_expense(
        trip,
        "chen",
        Money.of("9000", JPY),
        EqualSplit(["awanish", "bea", "chen", "dev"]),
        "Sushi in Tokyo layover",
    )

    try:
        PercentSplit({"awanish": "33.33", "bea": "33.33", "chen": "33.33"})
    except InvalidSplitError as exc:
        print("rejected:", exc)

    print("open currencies:", [c.code for c in svc.open_currencies(trip)])
    print("USD net:", {u: str(m) for u, m in svc.net_balances(trip, USD).items()})
    print("USD pairwise debts:", len(svc.debts(trip, USD)))
    for debt in svc.debts(trip, USD):
        print("   ", debt)
    plan = svc.suggest_settlements(trip, USD)
    print("USD simplified plan:", len(plan))
    for payment in plan:
        print("   ", payment)

    first = plan[0]
    svc.settle_up(trip, first.debtor, first.creditor, first.amount)
    print(f"settled: {first}")
    try:
        svc.settle_up(trip, first.debtor, first.creditor, Money.of("1.00", USD))
    except OverpaymentError as exc:
        print("rejected:", exc)

    svc.delete_expense(dinner.expense_id, "awanish")
    print(
        "after deleting dinner, USD net:",
        {u: str(m) for u, m in svc.net_balances(trip, USD).items()},
    )
    print("JPY plan:", [str(p) for p in svc.suggest_settlements(trip, JPY)])
    print("audit trail for", dinner.expense_id)
    for entry in svc.audit_trail(dinner.expense_id):
        print("   ", entry)


if __name__ == "__main__":
    main()
