"""Eviction policies as a Strategy.

The cache owns the values. A policy owns only the *order* of keys and answers
one question: "if something must go, which key?" The cache tells the policy
about every insert, access and removal, and asks victim() when it is full.

Every method here is O(1). None of them lock: the cache calls them while it
holds its own lock, so a policy never sees two threads at once.
"""
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable

from .config import EvictionKind
from .errors import CacheError
from .linked_list import DoublyLinkedList, Node


class EvictionPolicy[K](ABC):
    @abstractmethod
    def on_insert(self, key: K) -> None: ...

    @abstractmethod
    def on_access(self, key: K) -> None: ...

    @abstractmethod
    def on_remove(self, key: K) -> None: ...

    @abstractmethod
    def victim(self) -> K:
        """The key to evict next. Raises CacheError if nothing is tracked."""


class LRUPolicy[K](EvictionPolicy[K]):
    """Least recently used: a dict of key -> node, plus a doubly linked list."""

    def __init__(self) -> None:
        self._nodes: dict[K, Node[K]] = {}
        self._order: DoublyLinkedList[K] = DoublyLinkedList()

    def on_insert(self, key: K) -> None:
        node = Node(key)
        self._nodes[key] = node
        self._order.push_front(node)

    def on_access(self, key: K) -> None:
        self._order.move_to_front(self._nodes[key])

    def on_remove(self, key: K) -> None:
        self._order.remove(self._nodes.pop(key))

    def victim(self) -> K:
        last = self._order.back()
        if last is None:
            raise CacheError("victim() called on an empty LRU policy")
        return last.key


class FIFOPolicy[K](LRUPolicy[K]):
    """First in, first out: LRU's list, but a read never changes the order."""

    def on_access(self, key: K) -> None:
        pass


class LFUPolicy[K](EvictionPolicy[K]):
    """Least frequently used, O(1): one linked list per access count.

    Ties within the lowest count go to the least recently used key, because
    each bucket is itself an LRU list.
    """

    def __init__(self) -> None:
        self._nodes: dict[K, Node[K]] = {}
        self._counts: dict[K, int] = {}
        self._buckets: dict[int, DoublyLinkedList[K]] = {}
        self._min_count = 0

    def _bucket(self, count: int) -> DoublyLinkedList[K]:
        return self._buckets.setdefault(count, DoublyLinkedList())

    def _unlink(self, key: K) -> int:
        count = self._counts[key]
        bucket = self._buckets[count]
        bucket.remove(self._nodes[key])
        if not bucket:
            del self._buckets[count]
        return count

    def on_insert(self, key: K) -> None:
        node = Node(key)
        self._nodes[key] = node
        self._counts[key] = 1
        self._bucket(1).push_front(node)
        self._min_count = 1

    def on_access(self, key: K) -> None:
        count = self._unlink(key)
        if count == self._min_count and count not in self._buckets:
            self._min_count = count + 1
        self._counts[key] = count + 1
        self._bucket(count + 1).push_front(self._nodes[key])

    def on_remove(self, key: K) -> None:
        self._unlink(key)
        del self._nodes[key], self._counts[key]

    def victim(self) -> K:
        if not self._buckets:
            raise CacheError("victim() called on an empty LFU policy")
        if self._min_count not in self._buckets:
            # Only after a removal emptied the lowest bucket; rare, and
            # bounded by the number of distinct counts, not by cache size.
            self._min_count = min(self._buckets)
        return self._buckets[self._min_count].back().key  # type: ignore[union-attr]


class OrderedDictLRUPolicy[K](EvictionPolicy[K]):
    """The stdlib shortcut: OrderedDict is a dict plus a doubly linked list."""

    def __init__(self) -> None:
        self._order: OrderedDict[K, None] = OrderedDict()

    def on_insert(self, key: K) -> None:
        self._order[key] = None

    def on_access(self, key: K) -> None:
        self._order.move_to_end(key)

    def on_remove(self, key: K) -> None:
        del self._order[key]

    def victim(self) -> K:
        if not self._order:
            raise CacheError("victim() called on an empty LRU policy")
        return next(iter(self._order))


POLICY_FACTORIES: dict[EvictionKind, Callable[[], EvictionPolicy]] = {
    EvictionKind.LRU: LRUPolicy,
    EvictionKind.LFU: LFUPolicy,
    EvictionKind.FIFO: FIFOPolicy,
}


def make_policy(kind: EvictionKind) -> EvictionPolicy:
    """Build the policy a config names. Inject an instance to bypass this."""
    return POLICY_FACTORIES[kind]()
