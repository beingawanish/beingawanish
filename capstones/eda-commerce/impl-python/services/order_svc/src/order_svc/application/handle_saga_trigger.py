"""The order saga use case: run one trigger through the pure transition function inside the saga
kit's transaction, and turn the decision into outbox messages, the write-model status and, on
capture, the invoice (guide §4.2, ADR-0008, ADR-0009).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from edacommon.db import UnitOfWork
from edacommon.envelope import Causation
from edacommon.saga import SagaEngine, SagaRow, SagaStep
from edacommon.saga.repository import TRIGGER_DEADLINE, TRIGGER_OPERATOR

from order_svc.application import messages
from order_svc.application.ports import (
    DocumentStore,
    InvoiceRenderer,
    InvoiceRepository,
    OrderRecord,
    OrderRepository,
    StoredInvoice,
)
from order_svc.domain import saga as S
from order_svc.domain.invoice import Invoice, InvoiceLine, invoice_number
from order_svc.domain.money import Money

INVOICE_BUCKET = "invoices"


@dataclass(frozen=True)
class Ports:
    orders: OrderRepository
    invoices: InvoiceRepository


@dataclass
class OrderSaga:
    engine: SagaEngine
    ports_for: Callable[[UnitOfWork], Ports]
    renderer: InvoiceRenderer
    documents: DocumentStore
    timeouts: S.Timeouts
    mint: S.Mint

    # ------------------------------------------------------------------------------- entry points
    def start(self, uow: UnitOfWork, t: S.CheckoutSubmitted, order: OrderRecord, *, trigger_id: str) -> bool:
        ports = self.ports_for(uow)

        def decide(row: SagaRow | None, now: datetime) -> SagaStep | None:
            if row is not None:
                return None  # duplicate CheckoutSubmitted (new eventId, same orderId)
            ports.orders.create(order)
            return self._to_step(S.start(t, now, self.timeouts, self.mint), order, ports, now)

        return self.engine.handle(
            uow,
            saga_id=t.order_id,
            trigger_type=f"com.edacommerce.checkout.{t.kind}",
            trigger_id=trigger_id,
            decide=decide,
            correlation_id=t.order_id,
        ).applied

    def on_trigger(
        self,
        uow: UnitOfWork,
        order_id: str,
        t: S.Trigger,
        *,
        trigger_type: str,
        trigger_id: str | None,
        locked_row: SagaRow | None = None,
        causation: Causation | None = None,
    ) -> bool:
        ports = self.ports_for(uow)

        def decide(row: SagaRow | None, now: datetime) -> SagaStep | None:
            if row is None:
                # A reply for an order we never started: the CheckoutSubmitted is still in flight on
                # another topic (no cross-topic order). RetryLater lets it arrive first (ADR-0007).
                from edacommon.errors import RetryLater

                raise RetryLater(f"no saga for order {order_id} yet")
            data = S.SagaData.from_json(row.data)
            d = S.transition(
                S.State(row.state), data, row.step_attempts, t, now, self.timeouts, self.mint, deadline=row.deadline_at
            )
            if d.ignored:
                return SagaStep.ignore(row)
            order = ports.orders.get(order_id)
            assert order is not None, f"order row missing for saga {order_id}"
            return self._to_step(d, order, ports, now)

        result = self.engine.handle(
            uow,
            saga_id=order_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            decide=decide,
            locked_row=locked_row,
            causation=causation,
        )
        if result.applied and result.row is not None:
            ports.orders.set_status(
                order_id,
                S.customer_status(S.State(result.row.state)),
                result.row.version,
                result.row.updated_at or datetime.now().astimezone(),
            )
        return result.applied

    def on_deadline(self, uow: UnitOfWork, row: SagaRow) -> None:
        # Timer-caused: correlation stays the order, causation is null (Envelope doc).
        self.on_trigger(
            uow,
            row.saga_id,
            S.Deadline(),
            trigger_type=TRIGGER_DEADLINE,
            trigger_id=None,
            locked_row=row,
            causation=Causation(correlation_id=row.correlation_id),
        )

    def retry_step(self, uow: UnitOfWork, row: SagaRow) -> bool:
        if S.State(row.state) is not S.State.NEEDS_ATTENTION:
            return False
        return self.on_trigger(
            uow,
            row.saga_id,
            S.OperatorRetry(),
            trigger_type=TRIGGER_OPERATOR,
            trigger_id=None,
            locked_row=row,
            causation=Causation(correlation_id=row.correlation_id),
        )

    # ------------------------------------------------------------------------------- mapping
    def _to_step(self, d: S.Decision, order: OrderRecord, ports: Ports, now: datetime) -> SagaStep:
        msgs = [messages.command(c, d.data, order) for c in d.commands]
        for e in d.events:
            invoice = self._issue_invoice(d.data, order, ports, now) if e.name == "InvoiceIssued" else None
            msgs.append(messages.event(e, d.data, order, d.state, now, invoice))
        return SagaStep(
            state=d.state.value,
            data=d.data.to_json(),
            deadline_at=d.deadline,
            step_attempts=d.attempts,
            messages=msgs,
            terminal=d.terminal,
            outcome=d.outcome,
            decision_reached=d.decision_reached,
        )

    def _issue_invoice(self, d: S.SagaData, order: OrderRecord, ports: Ports, now: datetime) -> dict[str, Any]:
        """Gapless number + PDF + claim check, object first and event second (ADR-0009)."""
        existing = ports.invoices.for_order(d.order_id)
        if existing is not None:
            return {
                "invoiceId": existing.invoice_id,
                "invoiceNumber": existing.number,
                "document": existing.document,
                "issuedAt": existing.issued_at,
            }
        assert d.invoice_id
        number = invoice_number(now.year, ports.invoices.next_number(now.year))
        inv = Invoice(
            invoice_id=d.invoice_id,
            number=number,
            order_id=d.order_id,
            customer_id=d.customer_id,
            issued_at=now,
            lines=tuple(
                InvoiceLine(
                    x.sku,
                    x.product_name,
                    x.quantity,
                    Money(x.unit_price_minor, d.currency),
                    Money(x.line_total_minor, d.currency),
                )
                for x in d.lines
            ),
            total=Money(d.total_minor, d.currency),
            ship_to=tuple(
                str(order.ship_to[k])
                for k in ("recipientName", "line1", "line2", "postalCode", "city", "countryCode")
                if order.ship_to.get(k)
            ),
        )
        pdf = self.renderer.render(inv)
        # Deterministic key from business ids: a retry after a rollback overwrites the same object.
        key = f"order/{now:%Y}/{now:%m}/{d.order_id}/{d.invoice_id}.pdf"
        document = self.documents.put(INVOICE_BUCKET, key, pdf, "application/pdf")
        ports.invoices.save(StoredInvoice(d.invoice_id, d.order_id, number, document, now), d.total_minor, d.currency)
        return {"invoiceId": d.invoice_id, "invoiceNumber": number, "document": document, "issuedAt": now}
