"""agentkit — the tiny, stdlib-only kernel shared by every example in the book.

It provides three things and nothing else:

* ``MockLLM``  — a deterministic stand-in for a chat model with usage accounting.
* ``ToolRegistry`` — named tools with argument validation and structured errors.
* ``Trace``  — an ordered log of steps that examples print as their output.

Every pattern depends only on the ``LLM`` protocol (``complete(prompt, system="")``),
so swapping the mock for a real client is a one-line change (see ``agentkit/llm.py``).
"""

from .llm import LLM, MockLLM, Usage, rules, extract_json
from .tools import Tool, ToolError, ToolRegistry
from .trace import Trace

__all__ = [
    "LLM",
    "MockLLM",
    "Usage",
    "rules",
    "extract_json",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "Trace",
]
