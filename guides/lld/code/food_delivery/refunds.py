"""Refund rules: who cancelled, and how far the food got.

A customer who cancels before cooking starts gets everything back. Once the
kitchen is cooking they get half. After the food is ready they cannot
cancel at all. A restaurant rejection or a platform failure is never the
customer's fault, so those always refund in full.
"""
from abc import ABC, abstractmethod
from decimal import Decimal

from .config import RefundConfig
from .models import Order, to_money
from .status import Actor, OrderStatus


class RefundPolicy(ABC):
    @abstractmethod
    def customer_may_cancel(self, status: OrderStatus) -> bool:
        ...

    @abstractmethod
    def refund_for(self, order: Order, actor: Actor) -> Decimal:
        """Amount to return when actor ends the order in its current status."""


class StandardRefundPolicy(RefundPolicy):
    def __init__(self, config: RefundConfig):
        self._fractions = config.customer_refund_fraction

    def customer_may_cancel(self, status: OrderStatus) -> bool:
        return status in self._fractions

    def refund_for(self, order: Order, actor: Actor) -> Decimal:
        if actor is Actor.CUSTOMER:
            fraction = self._fractions.get(order.status, Decimal(0))
        else:
            fraction = Decimal(1)
        return to_money(order.bill.total * fraction)
