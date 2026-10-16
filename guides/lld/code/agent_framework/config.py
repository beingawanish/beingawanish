"""Configuration: every budget and limit the agent runtime enforces.

One frozen dataclass, validated on construction. The loop, the executor and
the memory read their numbers from here, so no limit hides as a literal.
"""
from dataclasses import dataclass

from agent_framework.errors import ConfigError


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 10                 # model calls per run
    max_total_tokens: int = 50_000      # input + output tokens per run, as the model reports them
    max_parallel_tools: int = 4         # worker threads for independent tool calls
    memory_token_budget: int = 8_000    # estimated tokens of history sent per model call
    chars_per_token: int = 4            # rough estimator used only for truncation
    max_tool_output_chars: int = 4_000  # tool output is clipped to this before the model sees it
    idempotency_ttl_seconds: float = 3_600.0

    def __post_init__(self) -> None:
        for name in ("max_steps", "max_total_tokens", "max_parallel_tools",
                     "memory_token_budget", "chars_per_token", "max_tool_output_chars"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be positive, got {getattr(self, name)}")
        if self.idempotency_ttl_seconds <= 0:
            raise ConfigError("idempotency_ttl_seconds must be positive")
