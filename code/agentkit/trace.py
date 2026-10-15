"""Ordered step log. Examples print their trace; verify.py compares it to the expected output."""

from __future__ import annotations

import threading


class Trace:
    def __init__(self, title: str) -> None:
        self.title = title
        self.lines: list[str] = []
        self._lock = threading.Lock()

    def step(self, label: str, detail: str = "") -> None:
        line = f"[{label}] {detail}".rstrip()
        with self._lock:
            self.lines.append(line)

    def note(self, text: str) -> None:
        with self._lock:
            self.lines.append(text)

    def render(self) -> str:
        bar = "=" * len(self.title)
        return "\n".join([self.title, bar, *self.lines])

    def print(self) -> None:
        print(self.render())
