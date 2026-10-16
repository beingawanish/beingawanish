"""Tests for expense sharing. Time and ids are fixed, so every run is identical."""

import random
import threading
import unittest
from datetime import UTC, datetime
from fractions import Fraction

from splitwise import (
    EUR,
    JPY,
    USD,
    AuditAction,
    BalanceLedger,
    ConfigError,
    Currency,
    CurrencyMismatchError,
    EqualSplit,
    ExactSplit,
    ExpenseAlreadyDeletedError,
    ExpenseService,
    FixedClock,
    GreedySimplifier,
    InvalidAmountError,
    InvalidInputError,
    InvalidSettlementError,
    InvalidSplitError,
    LedgerInvariantError,
    Money,
    NotAGroupMemberError,
    OverpaymentError,
    PercentSplit,
    SequentialIds,
    SharesSplit,
    SplitwiseConfig,
    UnknownGroupError,
    UnknownUserError,
    UnsupportedCurrencyError,
    allocate,
)

NOW = datetime(2026, 10, 16, 19, 30, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, USD)


def make_service(config: SplitwiseConfig | None = None) -> tuple[ExpenseService, str]:
    svc = ExpenseService(config=config, clock=FixedClock(NOW), ids=SequentialIds())
    for user_id in ("a", "b", "c", "d"):
        svc.register_user(user_id, user_id.upper())
    group = svc.create_group("trip", "a", ["b", "c", "d"])
    return svc, group.group_id


class MoneyTests(unittest.TestCase):
    def test_parses_exact_decimal_into_minor_units(self):
        self.assertEqual(usd("12.34").minor, 1234)
        self.assertEqual(Money.of("9000", JPY).minor, 9000)

    def test_rejects_float(self):
        with self.assertRaises(InvalidAmountError):
            Money.of(12.34, USD)  # type: ignore[arg-type]

    def test_rejects_more_decimal_places_than_the_currency_has(self):
        with self.assertRaises(InvalidAmountError):
            usd("1.005")
        with self.assertRaises(InvalidAmountError):
            Money.of("1.5", JPY)

    def test_rejects_garbage_and_infinity(self):
        for bad in ("abc", "Infinity", "NaN"):
            with self.subTest(bad=bad), self.assertRaises(InvalidAmountError):
                usd(bad)

    def test_arithmetic_refuses_mixed_currencies(self):
        with self.assertRaises(CurrencyMismatchError):
            usd("1.00") + Money.of("1.00", EUR)

    def test_formats_with_currency_exponent(self):
        self.assertEqual(str(usd("-0.05")), "USD -0.05")
        self.assertEqual(str(Money.of("500", JPY)), "JPY 500")

    def test_bad_currency_code_rejected(self):
        with self.assertRaises(InvalidAmountError):
            Currency("usd", 2)


class AllocateTests(unittest.TestCase):
    def test_odd_cent_goes_to_earliest_on_a_tie(self):
        self.assertEqual(allocate(100, [Fraction(1)] * 3), [34, 33, 33])

    def test_largest_remainder_wins_before_position(self):
        # exact shares 0.5, 0.75, 1.75 -> floors 0, 0, 1; the 2 leftover units go to the two 0.75s
        self.assertEqual(allocate(3, [Fraction(2), Fraction(3), Fraction(7)]), [0, 1, 2])

    def test_parts_always_sum_to_total(self):
        rng = random.Random(11)
        for _ in range(500):
            total = rng.randint(1, 1_000_000)
            weights = [Fraction(rng.randint(1, 97)) for _ in range(rng.randint(1, 9))]
            parts = allocate(total, weights)
            self.assertEqual(sum(parts), total)
            self.assertTrue(all(p >= 0 for p in parts))

    def test_all_zero_weights_rejected(self):
        with self.assertRaises(InvalidSplitError):
            allocate(100, [Fraction(0), Fraction(0)])


class SplitStrategyTests(unittest.TestCase):
    def test_equal_split(self):
        parts = EqualSplit(["a", "b", "c"]).split(usd("100.00"))
        self.assertEqual([m.minor for m in parts.values()], [3334, 3333, 3333])

    def test_exact_split_must_sum_to_total(self):
        split = ExactSplit({"a": usd("60.00"), "b": usd("30.00")})
        with self.assertRaisesRegex(
            InvalidSplitError, "sum to USD 90.00 but the total is USD 100.00"
        ):
            split.split(usd("100.00"))
        self.assertEqual(split.split(usd("90.00"))["a"], usd("60.00"))

    def test_exact_split_rejects_other_currency_part(self):
        with self.assertRaises(InvalidSplitError):
            ExactSplit({"a": Money.of("10.00", EUR)}).split(usd("10.00"))

    def test_percent_split_rounds_by_largest_remainder(self):
        parts = PercentSplit({"a": "33.33", "b": "33.33", "c": "33.34"}).split(usd("10.00"))
        self.assertEqual([m.minor for m in parts.values()], [333, 333, 334])

    def test_percent_split_must_sum_to_100(self):
        with self.assertRaises(InvalidSplitError):
            PercentSplit({"a": "50", "b": "49.99"})
        with self.assertRaises(InvalidSplitError):
            PercentSplit({"a": "150", "b": "-50"})

    def test_shares_split(self):
        parts = SharesSplit({"a": 1, "b": 2, "c": 1}).split(usd("10.00"))
        self.assertEqual([m.minor for m in parts.values()], [250, 500, 250])

    def test_shares_must_be_positive_ints(self):
        for bad in (0, -1, 1.5, True):
            with self.subTest(bad=bad), self.assertRaises(InvalidSplitError):
                SharesSplit({"a": bad})  # type: ignore[dict-item]

    def test_duplicates_and_empty_rejected(self):
        with self.assertRaises(InvalidSplitError):
            EqualSplit(["a", "a"])
        with self.assertRaises(InvalidSplitError):
            EqualSplit([])

    def test_non_positive_total_rejected(self):
        with self.assertRaises(InvalidAmountError):
            EqualSplit(["a"]).split(usd("0.00"))


class LedgerTests(unittest.TestCase):
    def test_opposite_debts_cancel_on_one_row(self):
        ledger = BalanceLedger()
        ledger.record_debt("a", "b", usd("10.00"))
        ledger.record_debt("b", "a", usd("4.00"))
        self.assertEqual(ledger.owed("a", "b", USD), usd("6.00"))
        self.assertEqual(ledger.owed("b", "a", USD), usd("0.00"))
        ledger.record_debt("b", "a", usd("6.00"))
        self.assertEqual(ledger.debts(USD), [])

    def test_net_sums_to_zero_and_currencies_stay_separate(self):
        ledger = BalanceLedger()
        ledger.record_debt("a", "b", usd("10.00"))
        ledger.record_debt("c", "b", usd("5.00"))
        ledger.record_debt("a", "c", Money.of("700", JPY))
        net = ledger.net(USD)
        self.assertEqual(net, {"a": usd("-10.00"), "b": usd("15.00"), "c": usd("-5.00")})
        self.assertEqual(ledger.net(JPY), {"a": Money.of("-700", JPY), "c": Money.of("700", JPY)})
        self.assertEqual([c.code for c in ledger.currencies()], ["JPY", "USD"])

    def test_owing_yourself_is_ignored(self):
        ledger = BalanceLedger()
        ledger.record_debt("a", "a", usd("10.00"))
        self.assertEqual(ledger.net(USD), {})


class SimplifierTests(unittest.TestCase):
    def test_greedy_matches_largest_creditor_with_largest_debtor(self):
        net = {"a": usd("-91.84"), "b": usd("144.67"), "c": usd("-17.83"), "d": usd("-35.00")}
        plan = GreedySimplifier().simplify(net)
        self.assertEqual(
            [str(p) for p in plan],
            [
                "a -> b: USD 91.84",
                "d -> b: USD 35.00",
                "c -> b: USD 17.83",
            ],
        )

    def test_plan_zeroes_every_balance_in_at_most_n_minus_1_payments(self):
        rng = random.Random(7)
        for _ in range(200):
            values = [rng.randint(-5000, 5000) for _ in range(rng.randint(2, 8))]
            values.append(-sum(values))
            net = {f"u{i}": Money(v, USD) for i, v in enumerate(values) if v != 0}
            plan = GreedySimplifier().simplify(net)
            remaining = {u: m.minor for u, m in net.items()}
            for p in plan:
                remaining[p.debtor] += p.amount.minor
                remaining[p.creditor] -= p.amount.minor
            self.assertTrue(all(v == 0 for v in remaining.values()))
            self.assertLessEqual(len(plan), max(len(net) - 1, 0))

    def test_greedy_is_not_always_minimal(self):
        # Optimal is 3 payments: d->a 60, then e and f pay b. Greedy takes 4.
        net = {"a": usd("60"), "b": usd("90"), "d": usd("-60"), "e": usd("-50"), "f": usd("-40")}
        self.assertEqual(len(GreedySimplifier().simplify(net)), 4)

    def test_unbalanced_input_is_a_bug(self):
        with self.assertRaises(LedgerInvariantError):
            GreedySimplifier().simplify({"a": usd("1.00")})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.group = make_service()

    def test_expense_updates_pairwise_and_net(self):
        self.svc.add_expense(self.group, "a", usd("90.00"), EqualSplit(["a", "b", "c"]), "dinner")
        self.assertEqual(
            [str(d) for d in self.svc.debts(self.group, USD)],
            ["b -> a: USD 30.00", "c -> a: USD 30.00"],
        )
        self.assertEqual(self.svc.net_balances(self.group, USD)["a"], usd("60.00"))

    def test_outsiders_rejected(self):
        self.svc.register_user("zed", "Zed")
        with self.assertRaises(NotAGroupMemberError):
            self.svc.add_expense(self.group, "a", usd("10.00"), EqualSplit(["a", "zed"]), "x")
        with self.assertRaises(UnknownGroupError):
            self.svc.add_expense("nope", "a", usd("10.00"), EqualSplit(["a"]), "x")
        with self.assertRaises(UnknownUserError):
            self.svc.create_group("g", "ghost")

    def test_member_added_later_can_join_expenses(self):
        self.svc.register_user("e", "E")
        self.svc.add_member(self.group, "e", actor="a")
        self.svc.add_expense(self.group, "e", usd("10.00"), EqualSplit(["a", "e"]), "coffee")
        self.assertEqual(self.svc.net_balances(self.group, USD)["e"], usd("5.00"))

    def test_input_validation(self):
        with self.assertRaises(InvalidInputError):
            self.svc.add_expense(self.group, "a", usd("1.00"), EqualSplit(["a"]), "   ")
        small = SplitwiseConfig(currencies=(USD,), max_participants=2)
        svc, group = make_service(small)
        with self.assertRaises(InvalidSplitError):
            svc.add_expense(group, "a", usd("3.00"), EqualSplit(["a", "b", "c"]), "too many")
        with self.assertRaises(UnsupportedCurrencyError):
            svc.add_expense(group, "a", Money.of("3", JPY), EqualSplit(["a"]), "yen")
        with self.assertRaises(ConfigError):
            SplitwiseConfig(max_participants=0)

    def test_settle_up_reduces_debt(self):
        self.svc.add_expense(self.group, "a", usd("90.00"), EqualSplit(["a", "b", "c"]), "dinner")
        self.svc.settle_up(self.group, "b", "a", usd("30.00"))
        self.assertNotIn("b", self.svc.net_balances(self.group, USD))
        self.assertEqual(self.svc.net_balances(self.group, USD)["a"], usd("30.00"))

    def test_settle_up_follows_simplified_plan_across_pairs(self):
        # b owes a 10 and a owes c 10. Simplified: b pays c directly; nobody else moves.
        self.svc.add_expense(self.group, "a", usd("10.00"), ExactSplit({"b": usd("10.00")}), "x")
        self.svc.add_expense(self.group, "c", usd("10.00"), ExactSplit({"a": usd("10.00")}), "y")
        [payment] = self.svc.suggest_settlements(self.group, USD)
        self.assertEqual(str(payment), "b -> c: USD 10.00")
        self.svc.settle_up(self.group, "b", "c", payment.amount)
        self.assertEqual(self.svc.net_balances(self.group, USD), {})

    def test_overpayment_and_self_payment_rejected(self):
        self.svc.add_expense(self.group, "a", usd("90.00"), EqualSplit(["a", "b", "c"]), "dinner")
        with self.assertRaises(OverpaymentError):
            self.svc.settle_up(self.group, "b", "a", usd("30.01"))
        with self.assertRaises(OverpaymentError):
            self.svc.settle_up(self.group, "a", "b", usd("1.00"))  # a is owed, not owing
        with self.assertRaises(InvalidSettlementError):
            self.svc.settle_up(self.group, "a", "a", usd("1.00"))

    def test_delete_reverses_balances_and_keeps_the_record(self):
        expense = self.svc.add_expense(
            self.group, "a", usd("90.00"), EqualSplit(["a", "b", "c"]), "dinner"
        )
        deleted = self.svc.delete_expense(expense.expense_id, actor="b")
        self.assertTrue(deleted.deleted)
        self.assertEqual(self.svc.net_balances(self.group, USD), {})
        with self.assertRaises(ExpenseAlreadyDeletedError):
            self.svc.delete_expense(expense.expense_id, actor="b")

    def test_audit_trail_records_every_money_change(self):
        expense = self.svc.add_expense(
            self.group, "a", usd("90.00"), EqualSplit(["a", "b", "c"]), "dinner"
        )
        self.svc.settle_up(self.group, "b", "a", usd("30.00"))
        self.svc.delete_expense(expense.expense_id, actor="c")
        actions = [e.action for e in self.svc.audit_trail()]
        self.assertEqual(
            actions[-3:],
            [
                AuditAction.EXPENSE_ADDED,
                AuditAction.SETTLEMENT_RECORDED,
                AuditAction.EXPENSE_DELETED,
            ],
        )
        seqs = [e.seq for e in self.svc.audit_trail()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        self.assertEqual([e.actor for e in self.svc.audit_trail(expense.expense_id)], ["a", "c"])


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_expenses_lose_no_cents(self):
        svc, group = make_service()
        barrier = threading.Barrier(8)

        def worker(payer: str) -> None:
            barrier.wait()
            for _ in range(50):
                svc.add_expense(group, payer, usd("10.00"), EqualSplit(["a", "b", "c"]), "round")

        threads = [threading.Thread(target=worker, args=(p,)) for p in "abcdabcd"]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        net = svc.net_balances(group, USD)
        self.assertEqual(sum(m.minor for m in net.values()), 0)
        # 400 expenses of $10. Each payer paid $1000. a absorbs the odd cent every time:
        # a owes 400 x 3.34 = 1336, b and c owe 400 x 3.33 = 1332 each, d owes nothing.
        self.assertEqual(
            net,
            {"a": usd("-336.00"), "b": usd("-332.00"), "c": usd("-332.00"), "d": usd("1000.00")},
        )

    def test_racing_settlements_only_one_wins(self):
        svc, group = make_service()
        svc.add_expense(group, "a", usd("20.00"), ExactSplit({"b": usd("20.00")}), "x")
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        outcomes_lock = threading.Lock()

        def pay() -> None:
            barrier.wait()
            try:
                svc.settle_up(group, "b", "a", usd("20.00"))
                result = "ok"
            except OverpaymentError:
                result = "rejected"
            with outcomes_lock:
                outcomes.append(result)

        threads = [threading.Thread(target=pay) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcomes), ["ok", "rejected"])
        self.assertEqual(svc.net_balances(group, USD), {})


if __name__ == "__main__":
    unittest.main()
