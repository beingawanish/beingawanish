"""The cart: what a customer wants, from exactly one restaurant.

The cart stores item ids and quantities only. Prices are read from the menu
at checkout, so a price change between "add" and "pay" can never leave a
stale number on the bill.

Not thread-safe on its own: the service owns every cart and touches them
only while holding its lock.
"""
from .errors import InvalidQuantityError, MixedRestaurantCartError


class Cart:
    def __init__(self, customer_id: str, max_quantity_per_line: int):
        self.customer_id = customer_id
        self._max_quantity = max_quantity_per_line
        self._restaurant_id: str | None = None
        self._quantities: dict[str, int] = {}

    @property
    def restaurant_id(self) -> str | None:
        return self._restaurant_id

    @property
    def is_empty(self) -> bool:
        return not self._quantities

    def items(self) -> dict[str, int]:
        return dict(self._quantities)

    def add(self, restaurant_id: str, item_id: str, quantity: int,
            *, replace: bool = False) -> None:
        if quantity < 1:
            raise InvalidQuantityError(f"quantity must be at least 1, got {quantity}")
        if self._restaurant_id not in (None, restaurant_id):
            if not replace:
                raise MixedRestaurantCartError(
                    f"cart holds items from {self._restaurant_id}; "
                    f"clear it or pass replace=True to order from {restaurant_id}")
            self.clear()
        new_quantity = self._quantities.get(item_id, 0) + quantity
        if new_quantity > self._max_quantity:
            raise InvalidQuantityError(
                f"at most {self._max_quantity} of one item per order")
        self._restaurant_id = restaurant_id
        self._quantities[item_id] = new_quantity

    def remove(self, item_id: str, quantity: int | None = None) -> None:
        """Remove some (or, with quantity=None, all) of one item."""
        current = self._quantities.get(item_id, 0)
        if current == 0:
            return
        if quantity is None or quantity >= current:
            del self._quantities[item_id]
        elif quantity < 1:
            raise InvalidQuantityError(f"quantity must be at least 1, got {quantity}")
        else:
            self._quantities[item_id] = current - quantity
        if not self._quantities:
            self._restaurant_id = None

    def clear(self) -> None:
        self._quantities.clear()
        self._restaurant_id = None
