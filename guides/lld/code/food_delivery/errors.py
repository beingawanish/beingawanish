"""Domain errors for food delivery, grouped by who can fix them."""


class FoodDeliveryError(Exception):
    """Base of every error the food-delivery domain can raise."""


# -- catalogue: the customer picks something else ----------------------

class RestaurantNotFoundError(FoodDeliveryError):
    pass


class RestaurantClosedError(FoodDeliveryError):
    pass


class MenuItemNotFoundError(FoodDeliveryError):
    pass


class ItemUnavailableError(FoodDeliveryError):
    pass


# -- cart and checkout: the customer fixes their input ------------------

class MixedRestaurantCartError(FoodDeliveryError):
    """The cart holds items from one restaurant; this item is from another."""


class InvalidQuantityError(FoodDeliveryError):
    pass


class EmptyCartError(FoodDeliveryError):
    pass


class InvalidCouponError(FoodDeliveryError):
    """No discount rule recognises this code."""


class CouponNotApplicableError(FoodDeliveryError):
    """The code exists, but this cart does not qualify (e.g. minimum spend)."""


class IdempotencyKeyReusedError(FoodDeliveryError):
    """Same key, different request: a client bug, not a retry."""


# -- lifecycle: the caller asked for an illegal move --------------------

class OrderNotFoundError(FoodDeliveryError):
    pass


class InvalidTransitionError(FoodDeliveryError):
    pass


class CancellationNotAllowedError(FoodDeliveryError):
    pass


# -- dispatch ----------------------------------------------------------

class PartnerNotFoundError(FoodDeliveryError):
    pass


class PartnerMismatchError(FoodDeliveryError):
    """This partner does not hold the offer or the assignment for the order."""


class NoActiveOfferError(FoodDeliveryError):
    pass
