"""Parallelization: run independent calls concurrently, aggregate in code.

``fan_out`` never lets one branch's exception kill the others: every branch returns
a ``Branch`` with either a value or an error, and the *aggregator* decides whether a
failed branch means fail-closed, retry, or ignore.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class Branch:
    name: str
    value: Any = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def fan_out(tasks: dict[str, Callable[[], Any]], max_workers: int = 8, timeout: float = 30.0) -> list[Branch]:
    """Run each zero-arg callable concurrently. Results come back in *input order*."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        out = []
        for name, fut in futures.items():
            try:
                out.append(Branch(name, value=fut.result(timeout=timeout)))
            except Exception as exc:  # captured, not raised: the aggregator decides
                out.append(Branch(name, error=f"{type(exc).__name__}: {exc}"))
        return out


def majority_vote(values: list[Any], min_agreement: float = 0.5) -> tuple[Optional[Any], float]:
    """Return (winner, agreement). Winner is None if no value exceeds ``min_agreement``."""
    if not values:
        return None, 0.0
    winner, count = Counter(values).most_common(1)[0]
    agreement = count / len(values)
    return (winner if agreement > min_agreement else None), agreement
