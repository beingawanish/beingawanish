"""Domain errors for the agent runtime.

Two families with two different fates:
  * ToolError and its subclasses never escape the executor. Each one becomes
    a tool_result with is_error=True, so the model can read it and recover.
  * Everything else (config, registration, model failures) is a programming or
    infrastructure fault. Those propagate to the caller.
"""


class AgentError(Exception):
    """Root of every error this package raises."""


class ConfigError(AgentError):
    """A config value is out of range."""


class ToolRegistrationError(AgentError):
    """A tool could not be registered: bad name, duplicate, or no usable schema."""


class SchemaError(ToolRegistrationError):
    """A type hint cannot be expressed as JSON Schema."""


class ConversationError(AgentError):
    """A message would break the user/assistant alternation."""


class ModelError(AgentError):
    """The model call failed, or the model broke the message protocol."""


class ToolError(AgentError):
    """Base for failures that are reported back to the model as error results."""


class ToolNotFoundError(ToolError):
    """The model asked for a tool that is not registered."""


class ToolInputError(ToolError):
    """The model's input does not match the tool's schema."""


class PermissionDeniedError(ToolError):
    """Policy, a hook, or a human said no."""


class ToolExecutionError(ToolError):
    """The tool's own code raised."""
