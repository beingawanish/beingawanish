"""Mock tools with argument validation and structured errors.

A tool is a plain Python function plus a parameter spec. The registry validates
arguments *before* calling the function and turns every failure into a
``ToolError`` whose message is safe to show to a model ("tool errors are
observations, not exceptions").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """An error the agent should see as an observation and may recover from."""


@dataclass
class Tool:
    name: str
    fn: Callable[..., Any]
    description: str
    params: dict[str, type] = field(default_factory=dict)  # required params and their types

    def spec(self) -> str:
        args = ", ".join(f"{k}: {t.__name__}" for k, t in self.params.items())
        return f"{self.name}({args}) — {self.description}"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self.log: list[tuple[str, dict, str]] = []  # (name, args, "ok"|"error")

    def register(self, name: str, description: str, **params: type):
        """Decorator: ``@tools.register("lookup", "Find a customer", customer_id=str)``."""

        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = Tool(name, fn, description, params)
            return fn

        return wrap

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> str:
        return "\n".join(t.spec() for t in self._tools.values())

    def call(self, name: str, args: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            self.log.append((name, args, "error"))
            raise ToolError(f"unknown tool '{name}'. Available: {', '.join(self._tools)}")
        missing = [p for p in tool.params if p not in args]
        if missing:
            self.log.append((name, args, "error"))
            raise ToolError(f"{name}: missing argument(s) {missing}")
        for p, typ in tool.params.items():
            if not isinstance(args[p], typ):
                self.log.append((name, args, "error"))
                raise ToolError(f"{name}: argument '{p}' must be {typ.__name__}")
        try:
            result = tool.fn(**args)
        except ToolError:
            self.log.append((name, args, "error"))
            raise
        except Exception as exc:  # never let a tool crash the agent loop
            self.log.append((name, args, "error"))
            raise ToolError(f"{name} failed: {exc}") from None
        self.log.append((name, args, "ok"))
        return result
