"""payment.commands.v1 handlers."""

from __future__ import annotations

from collections.abc import Callable

from contracts_py.records import AuthorizePayment, CapturePayment, RefundPayment, VoidPayment
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock

from payment_svc.application.payments import Payments

TOPICS = [AuthorizePayment.TOPIC]


def build_registry(payments_for: Callable[[UnitOfWork], Payments], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(AuthorizePayment)
    def on_authorize(cmd: AuthorizePayment, ctx: MessageContext, uow: UnitOfWork) -> None:
        payments_for(uow).authorize(
            order_id=cmd.order_id,
            payment_id=cmd.payment_id,
            customer_id=cmd.customer_id,
            amount_minor=cmd.amount.amount_minor,
            currency=cmd.amount.currency,
            token=cmd.payment_method_token,
            now=clock.now(),
        )

    @reg.handler(CapturePayment)
    def on_capture(cmd: CapturePayment, ctx: MessageContext, uow: UnitOfWork) -> None:
        payments_for(uow).capture(payment_id=cmd.payment_id, amount_minor=cmd.amount.amount_minor, now=clock.now())

    @reg.handler(VoidPayment)
    def on_void(cmd: VoidPayment, ctx: MessageContext, uow: UnitOfWork) -> None:
        payments_for(uow).void(order_id=cmd.order_id, payment_id=cmd.payment_id, now=clock.now())

    @reg.handler(RefundPayment)
    def on_refund(cmd: RefundPayment, ctx: MessageContext, uow: UnitOfWork) -> None:
        payments_for(uow).refund(
            order_id=cmd.order_id,
            payment_id=cmd.payment_id,
            refund_id=cmd.refund_id,
            return_id=cmd.return_id,
            amount_minor=cmd.amount.amount_minor,
            currency=cmd.amount.currency,
            now=clock.now(),
        )

    return reg
