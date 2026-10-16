"""Tools: the abstraction, a function-backed implementation, and the registry.

A Tool is three facts the model sees (name, description, input_schema) plus
two facts the runtime uses (side_effects, parallel_safe) plus run().
The registry's @tool decorator turns a typed function into a FunctionTool.
"""
import inspect
import json
import logging
import re
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from agent_framework.errors import ToolNotFoundError, ToolRegistrationError
from agent_framework.schema import JsonSchema, schema_from_function

log = logging.getLogger(__name__)

# Same shape the Claude API accepts for tool names.
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class Tool(ABC):
    """Anything the model can call. Subclass it directly for stateful tools."""

    name: str
    description: str
    input_schema: JsonSchema
    side_effects: bool = False   # changes the world: email, payment, write
    parallel_safe: bool = True   # may run alongside other calls in one batch

    @abstractmethod
    def run(self, tool_input: dict[str, Any]) -> str:
        """Do the work and return text for the model. Input is already validated."""

    def definition(self) -> dict[str, Any]:
        """What the model is shown: the provider-neutral tool definition."""
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


class FunctionTool(Tool):
    """A Tool backed by a plain typed function."""

    def __init__(self, fn: Callable[..., Any], name: str, description: str,
                 side_effects: bool, parallel_safe: bool) -> None:
        self._fn = fn
        self.name = name
        self.description = description
        self.input_schema = schema_from_function(fn)
        self.side_effects = side_effects
        self.parallel_safe = parallel_safe

    def run(self, tool_input: dict[str, Any]) -> str:
        result = self._fn(**tool_input)
        if isinstance(result, str):
            return result
        return json.dumps(result, sort_keys=True, default=str)


class ToolRegistry:
    """Name -> Tool. Registration happens at startup; lookups happen from
    many tool threads, so both go through one lock."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.Lock()  # guards _tools

    def register(self, tool: Tool) -> Tool:
        if not _NAME_RE.match(tool.name):
            raise ToolRegistrationError(f"invalid tool name {tool.name!r}")
        if not tool.description.strip():
            raise ToolRegistrationError(f"tool {tool.name!r} needs a description")
        with self._lock:
            if tool.name in self._tools:
                raise ToolRegistrationError(f"tool {tool.name!r} is already registered")
            self._tools[tool.name] = tool
        log.info("registered tool %s (side_effects=%s)", tool.name, tool.side_effects)
        return tool

    def tool(self, name: str | None = None, description: str | None = None, *,
             side_effects: bool = False,
             parallel_safe: bool | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator. The function stays callable as-is; a FunctionTool is registered.

        Description defaults to the docstring. Side-effecting tools default to
        parallel_safe=False, so their order in a batch is preserved.
        """
        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            desc = description or inspect.getdoc(fn) or ""
            safe = (not side_effects) if parallel_safe is None else parallel_safe
            self.register(FunctionTool(fn, name or fn.__name__, desc, side_effects, safe))
            return fn
        return decorate

    def get(self, name: str) -> Tool:
        with self._lock:
            tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"no tool named {name!r}")
        return tool

    def definitions(self) -> list[dict[str, Any]]:
        """Sorted by name: a stable tool list keeps a provider's prompt cache warm."""
        with self._lock:
            tools = sorted(self._tools.values(), key=lambda t: t.name)
        return [t.definition() for t in tools]
