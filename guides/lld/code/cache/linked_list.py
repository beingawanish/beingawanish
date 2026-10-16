"""A doubly linked list with sentinel nodes: the O(1) half of an LRU cache.

A dict finds a key's node in O(1). This list then moves, unlinks or appends
that node in O(1), because every node knows both neighbours. Two sentinels
(head and tail) mean the list is never "really" empty, so no method needs an
if-branch for the first or last node.

Order convention: front = most recently touched, back = next to go.
"""
from collections.abc import Iterator


class Node[K]:
    __slots__ = ("key", "prev", "next")

    def __init__(self, key: K) -> None:
        self.key = key
        self.prev: Node[K] | None = None
        self.next: Node[K] | None = None


class DoublyLinkedList[K]:
    """Not thread-safe on its own; the owning cache holds the lock."""

    def __init__(self) -> None:
        self._head: Node[K] = Node(None)  # type: ignore[arg-type]  # sentinel
        self._tail: Node[K] = Node(None)  # type: ignore[arg-type]  # sentinel
        self._head.next = self._tail
        self._tail.prev = self._head
        self._length = 0

    def __len__(self) -> int:
        return self._length

    def push_front(self, node: Node[K]) -> None:
        first = self._head.next
        node.prev, node.next = self._head, first
        self._head.next = node
        first.prev = node  # type: ignore[union-attr]
        self._length += 1

    def remove(self, node: Node[K]) -> None:
        node.prev.next = node.next  # type: ignore[union-attr]
        node.next.prev = node.prev  # type: ignore[union-attr]
        node.prev = node.next = None
        self._length -= 1

    def move_to_front(self, node: Node[K]) -> None:
        self.remove(node)
        self.push_front(node)

    def back(self) -> Node[K] | None:
        """The node at the back (least recently touched), or None if empty."""
        last = self._tail.prev
        return None if last is self._head else last

    def __iter__(self) -> Iterator[K]:
        """Keys from front (newest) to back (oldest)."""
        node = self._head.next
        while node is not self._tail:
            yield node.key  # type: ignore[union-attr]
            node = node.next  # type: ignore[union-attr]
