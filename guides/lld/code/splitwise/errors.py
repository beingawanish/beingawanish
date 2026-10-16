"""Domain exceptions for expense sharing.

One base class, one subclass per failure a caller might handle differently.
Nobody parses message strings: the type says what went wrong.
"""


class SplitwiseError(Exception):
    """Base class for every expense-sharing failure."""


class ConfigError(SplitwiseError):
    """The configuration itself is invalid."""


class InvalidInputError(SplitwiseError):
    """A text field is blank or too long."""


class InvalidAmountError(SplitwiseError):
    """An amount is malformed: a float, too many decimal places, or not positive."""


class CurrencyMismatchError(SplitwiseError):
    """Two amounts in different currencies were combined."""


class UnsupportedCurrencyError(SplitwiseError):
    """The currency is not in the configured list."""


class InvalidSplitError(SplitwiseError):
    """A split is malformed, or its parts do not add up to the total."""


class NotFoundError(SplitwiseError):
    """Base for lookups of ids that do not exist."""


class UnknownUserError(NotFoundError):
    """No user has this id."""


class UnknownGroupError(NotFoundError):
    """No group has this id."""


class UnknownExpenseError(NotFoundError):
    """No expense has this id."""


class DuplicateIdError(SplitwiseError):
    """An object with this id already exists."""


class NotAGroupMemberError(SplitwiseError):
    """A user took part in a group action without being a member."""


class InvalidSettlementError(SplitwiseError):
    """A settle-up payment is malformed, such as paying yourself."""


class OverpaymentError(InvalidSettlementError):
    """A payment would create debt instead of reducing it."""


class ExpenseAlreadyDeletedError(SplitwiseError):
    """The expense was deleted before; deleting twice would double-reverse it."""


class LedgerInvariantError(SplitwiseError):
    """Net balances do not sum to zero. This is a bug, never user error."""
