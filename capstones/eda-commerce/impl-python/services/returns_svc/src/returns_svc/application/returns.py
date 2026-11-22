"""returns-svc use cases: the eligibility projection, ``POST /returns``, the ops decision, and every saga
trigger run through the pure transition function inside the saga kit's transaction (ADR-0008).

Pass-through states (REQUESTED, AUTHORIZED, EXPIRED, REJECTED with nothing pending) are followed by an
internal ``CONTINUE`` trigger in the same transaction, so the transition log has one row per edge of
architecture §6.1 and nobody observes a half-step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from edacommon.db import UnitOfWork
from edacommon.envelope import Causation
from edacommon.errors import DomainError
from edacommon.ids import Clock
from edacommon.logging import get_logger
from edacommon.saga import SagaEngine, SagaRow, SagaStep
from edacommon.saga.repository import TRIGGER_DEADLINE, TRIGGER_OPERATOR, SagaRepository

from returns_svc.application import messages
from returns_svc.application.ports import ReturnRecord, ReturnsRepository, StoredLine
from returns_svc.domain import saga as S
from returns_svc.domain.policy import (
    NotEligible,
    OrderLine,
    OrderView,
    check_eligibility,
    refundable_shipping_fee,
    returnable,
    shipping_fee_of,
)

log = get_logger(__name__)
TRIGGER_AUTO = "AUTO"  # internal CONTINUE through a pass-through state
DEFAULT_WAREHOUSE = "wh-berlin-1"
DECISIONS = frozenset({"APPROVE", "REJECT", "RETRY_REFUND", "CLOSE_WITHOUT_REFUND"})


class ReturnNotFound(DomainError):
    problem_type = "not-found"
    status = 404


class ReturnNotWaiting(DomainError):
    problem_type = "return-not-awaiting-decision"
    status = 409


@dataclass
class ReturnsSaga:
    engine: SagaEngine
    repo_for: Callable[[UnitOfWork], ReturnsRepository]
    policy: S.Policy
    window: timedelta
    new_id: Callable[[], str]
    clock: Clock

    # ---------------------------------------------------------------- eligibility projection
    def on_order_placed(
        self,
        uow: UnitOfWork,
        *,
        order_id: str,
        customer_id: str,
        currency: str,
        total_minor: int,
        lines: tuple[OrderLine, ...],
        ship_to: dict[str, Any],
        now: datetime,
    ) -> None:
        self.repo_for(uow).placed(
            order_id=order_id,
            customer_id=customer_id,
            currency=currency,
            total_minor=total_minor,
            shipping_fee_minor=shipping_fee_of(total_minor, lines),
            lines=lines,
            ship_to=ship_to,
            now=now,
        )

    def on_order_fact(self, uow: UnitOfWork, order_id: str, now: datetime, **facts: Any) -> None:
        if not self.repo_for(uow).set_view_fact(order_id, now, **facts):
            # Same topic and key as OrderPlaced, so this only happens for orders placed before this
            # service existed (or retention); facts about unknown orders are not needed.
            log.warning("order fact for an unknown order; ignored", order_id=order_id, facts=sorted(facts))

    # -------------------------------------------------------------------------- POST /returns
    def request(
        self,
        uow: UnitOfWork,
        *,
        caller: str,
        is_ops: bool,
        order_id: str,
        lines: list[tuple[str, int]],
        reason: str,
        comment: str | None,
        now: datetime,
    ) -> ReturnRecord:
        repo = self.repo_for(uow)
        view = repo.view(order_id, for_update=True)  # serialises concurrent returns of one order
        if view is None or (view.customer_id != caller and not is_ops):
            raise ReturnNotFound(f"no order {order_id}")
        try:
            chosen = check_eligibility(view, lines, repo.returned_quantities(order_id), now, self.window)
        except NotEligible as exc:
            raise DomainError(exc.detail, problem_type=exc.problem_type, status=422) from exc
        return_id = self.new_id()
        fee = refundable_shipping_fee(view, reason, return_id)
        if fee:
            repo.claim_shipping_fee(order_id, return_id)
        data = S.SagaData(
            return_id=return_id,
            order_id=order_id,
            customer_id=view.customer_id,
            currency=view.currency,
            reason=reason,
            lines=chosen,
            shipping_fee_minor=fee,
            pickup_from=dict(view.ship_to or {}),
            warehouse_id=view.warehouse_id or DEFAULT_WAREHOUSE,
            payment_id=view.payment_id,
            comment=comment,
            requested_at=now.isoformat(),
        )
        record = ReturnRecord(
            return_id=return_id,
            order_id=order_id,
            customer_id=view.customer_id,
            reason=reason,
            comment=comment,
            status="REQUESTED",
            currency=view.currency,
            requested_at=now,
            lines=tuple(StoredLine(x.line_id, x.sku, x.quantity, x.unit_price_minor) for x in chosen),
        )
        repo.insert(record, now)
        # An HTTP request starts the flow: correlation = returnId, no causing event (Envelope doc).
        causation = Causation(correlation_id=return_id)
        self._run(uow, return_id, None, "HTTP", None, causation, first=S.start(data))
        out = repo.get(return_id)
        assert out is not None
        return out

    # -------------------------------------------------------------------- ops decision
    def decide(self, uow: UnitOfWork, *, return_id: str, decision: str, note: str | None) -> ReturnRecord:
        repo = self.repo_for(uow)
        row = SagaRepository(uow.session).load_for_update(return_id)
        if row is None:
            raise ReturnNotFound(f"no return {return_id}")
        state = S.State(row.state)
        allowed = {S.State.MANUAL_REVIEW: {"APPROVE", "REJECT"}, S.State.REFUND_REVIEW: {"RETRY_REFUND", "CLOSE_WITHOUT_REFUND"}}
        if decision not in allowed.get(state, set()):
            raise ReturnNotWaiting(f"return {return_id} is {state.value}; {decision} is not possible now")
        applied = self._run(
            uow,
            return_id,
            S.Decide(decision, note),
            TRIGGER_OPERATOR,
            None,
            Causation(correlation_id=row.correlation_id),
            locked=row,
        )
        if not applied:
            raise ReturnNotWaiting(f"return {return_id} is not waiting for {decision}")
        out = repo.get(return_id)
        assert out is not None
        return out

    # ------------------------------------------------------------------- saga triggers
    def on_trigger(self, uow: UnitOfWork, return_id: str, t: S.Trigger, *, trigger_type: str, trigger_id: str | None) -> bool:
        if SagaRepository(uow.session).get(return_id) is None:
            # Replies only exist after our own commit, so an unknown id is not ours (another build's
            # database, or a hand-replayed message): record nothing.
            log.warning("reply for an unknown return; ignored", return_id=return_id, event_type=trigger_type)
            return False
        return self._run(uow, return_id, t, trigger_type, trigger_id, None)

    def on_deadline(self, uow: UnitOfWork, row: SagaRow) -> None:
        self._run(
            uow, row.saga_id, S.Deadline(), TRIGGER_DEADLINE, None, Causation(correlation_id=row.correlation_id), locked=row
        )

    def retry_step(self, uow: UnitOfWork, row: SagaRow) -> bool:
        state = S.State(row.state)
        if state in (S.State.CLOSED, *S.WAITING_FOR_HUMAN):
            return False  # humans decide through POST /ops/returns/{id}/decision
        return self._run(
            uow, row.saga_id, S.OperatorRetry(), TRIGGER_OPERATOR, None, Causation(correlation_id=row.correlation_id), locked=row
        )

    def return_id_for_refund(self, uow: UnitOfWork, refund_id: str) -> str | None:
        return self.repo_for(uow).return_id_for_refund(refund_id)

    # --------------------------------------------------------------------------- engine
    def _run(
        self,
        uow: UnitOfWork,
        return_id: str,
        t: S.Trigger | None,
        trigger_type: str,
        trigger_id: str | None,
        causation: Causation | None,
        *,
        first: S.Decision | None = None,
        locked: SagaRow | None = None,
    ) -> bool:
        repo = self.repo_for(uow)
        ids = S.Ids(new_id=self.new_id, rma_number=lambda: _rma(repo, self.clock.now().year))
        last: list[S.Decision] = []

        def decide(row: SagaRow | None, now: datetime) -> SagaStep | None:
            if row is None:
                if first is None:
                    return None
                d = first
            else:
                assert t is not None
                data = S.SagaData.from_json(row.data)
                d = S.transition(S.State(row.state), data, row.step_attempts, t, now, self.policy, ids, deadline=row.deadline_at)
                if d.ignored:
                    if d.data.notes != data.notes:
                        log.info("late or irrelevant reply recorded", return_id=return_id, trigger=trigger_type)
                    return SagaStep.ignore(row)
            last.append(d)
            return self._to_step(d, now)

        result = self.engine.handle(
            uow,
            saga_id=return_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            decide=decide,
            correlation_id=return_id,
            causation=causation,
            locked_row=locked,
        )
        if not result.applied:
            return False
        # Pass-through states continue at once, in the same transaction (one transition row each).
        while last and last[-1].needs_continue:
            d0 = last[-1]
            last.clear()
            t2: S.Trigger = S.Continue()

            def cont(row: SagaRow | None, now: datetime, trig: S.Trigger = t2) -> SagaStep | None:
                assert row is not None
                d = S.transition(
                    S.State(row.state), S.SagaData.from_json(row.data), row.step_attempts, trig, now, self.policy, ids
                )
                if d.ignored:
                    return SagaStep.ignore(row)
                last.append(d)
                return self._to_step(d, now)

            self.engine.handle(
                uow, saga_id=return_id, trigger_type=TRIGGER_AUTO, trigger_id=None, decide=cont, causation=causation
            )
            if not last:
                log.error("pass-through state did not continue", return_id=return_id, state=d0.state.value)
                break
        row = SagaRepository(uow.session).get(return_id)
        assert row is not None
        self._project(repo, row)
        return True

    def _to_step(self, d: S.Decision, now: datetime) -> SagaStep:
        msgs = [messages.command(c, d.data, now) for c in d.commands] + [messages.event(e, d.data, now) for e in d.events]
        return SagaStep(
            state=d.state.value,
            data=d.data.to_json(),
            deadline_at=d.deadline,
            step_attempts=d.attempts,
            messages=msgs,
            terminal=d.terminal,
            outcome=d.outcome,
        )

    def _project(self, repo: ReturnsRepository, row: SagaRow) -> None:
        """Keep ``return_request`` (the API's read side) in step with the saga row, same transaction."""
        current = repo.get(row.saga_id)
        assert current is not None
        state = S.State(row.state)
        d = S.SagaData.from_json(row.data)
        outcomes: dict[str, list[dict[str, Any]]] = {}
        for r in d.results:
            outcomes.setdefault(str(r["line_id"]), []).append(r)
        repo.update(
            replace(
                current,
                status=S.api_status(state, d),
                rma_number=d.rma_number,
                refund_minor=d.refund_minor if d.refund_id else None,
                refund_id=d.refund_id,
                label=d.label,
                parcel_due_by=datetime.fromisoformat(d.parcel_due_by) if d.parcel_due_by else None,
                counts_against_order=S.counts_against_order(state, d),
                lines=tuple(replace(x, inspection=tuple(outcomes.get(x.line_id, ()))) for x in current.lines),
            ),
            self.clock.now(),
        )

    # --------------------------------------------------------------------------- queries
    def view_of_order(self, uow: UnitOfWork, order_id: str) -> tuple[OrderView, dict[str, int], list[ReturnRecord]] | None:
        repo = self.repo_for(uow)
        view = repo.view(order_id)
        if view is None:
            return None
        return view, returnable(view, repo.returned_quantities(order_id)), repo.for_order(order_id)


def _rma(repo: ReturnsRepository, year: int) -> str:
    return f"RMA-{year}-{repo.next_rma(year):06d}"
