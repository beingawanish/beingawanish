"""Domain errors for the cache.

The config and entry errors also subclass ValueError, so callers that only
know "bad argument" still catch them. A miss is never an error: get() returns
a default instead of raising.
"""


class CacheError(Exception):
    """Base of every error the cache package raises."""


class CacheConfigError(CacheError, ValueError):
    """A CacheConfig field is out of range."""


class InvalidEntryError(CacheError, ValueError):
    """A put() argument (ttl or size) is out of range."""


class EntryTooLargeError(InvalidEntryError):
    """One entry is bigger than the whole cache's max_size."""


class LoadError(CacheError):
    """The read-through loader failed; the original error is the __cause__."""


class SweeperStateError(CacheError):
    """The sweeper was started twice, or stopped before it started."""
