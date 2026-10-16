"""JSON Schema: derive it from type hints, then validate model input against it.

Derivation runs once, at registration, and fails loudly on a hint it cannot
express. Validation runs on every call and collects every problem, so the
model gets one error result listing all of them instead of a drip of retries.
"""
import inspect
import types
import typing
from collections.abc import Callable
from typing import Annotated, Any, Literal, Union

from agent_framework.errors import SchemaError, ToolInputError

JsonSchema = dict[str, Any]

_PRIMITIVES: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _type_schema(hint: Any, where: str) -> JsonSchema:
    if hint in _PRIMITIVES:
        return {"type": _PRIMITIVES[hint]}
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is Literal:
        if not all(isinstance(a, str) for a in args):
            raise SchemaError(f"{where}: only string Literals are supported")
        return {"type": "string", "enum": list(args)}
    if origin is list and len(args) == 1:
        return {"type": "array", "items": _type_schema(args[0], where)}
    if hint is dict or origin is dict:
        return {"type": "object"}
    raise SchemaError(f"{where}: unsupported type hint {hint!r}")


def _unwrap_optional(hint: Any) -> tuple[Any, bool]:
    """`T | None` -> (T, True). Anything else -> (hint, False)."""
    if typing.get_origin(hint) in (Union, types.UnionType):
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(hint)) == 2:
            return args[0], True
    return hint, False


def schema_from_function(fn: Callable[..., Any]) -> JsonSchema:
    """Build an object schema from fn's parameters.

    Annotated[T, "text"] becomes the property description. A parameter is
    required unless it has a default or is typed `T | None`.
    """
    hints = typing.get_type_hints(fn, include_extras=True)
    properties: dict[str, JsonSchema] = {}
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        where = f"{fn.__name__}({name})"
        if param.kind not in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            raise SchemaError(f"{where}: *args and **kwargs cannot be described")
        if name not in hints:
            raise SchemaError(f"{where}: missing type hint")
        hint, description = hints[name], None
        if typing.get_origin(hint) is Annotated:
            hint, *extras = typing.get_args(hint)
            description = next((e for e in extras if isinstance(e, str)), None)
        hint, optional = _unwrap_optional(hint)
        prop = _type_schema(hint, where)
        if description:
            prop["description"] = description
        properties[name] = prop
        if param.default is inspect.Parameter.empty and not optional:
            required.append(name)
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


def _check(value: Any, schema: JsonSchema, path: str, problems: list[str]) -> None:
    expected = schema.get("type")
    # bool is a subclass of int in Python; JSON keeps them apart, so do we.
    ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
        None: True,
    }[expected]
    if not ok:
        problems.append(f"{path}: expected {expected}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if expected == "array" and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", problems)
    if expected == "object" and "properties" in schema:
        props = schema["properties"]
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}.{key}: required")
        for key, item in value.items():
            if key in props:
                _check(item, props[key], f"{path}.{key}", problems)
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path}.{key}: unexpected property")


def validate(value: Any, schema: JsonSchema) -> None:
    """Raise ToolInputError listing every mismatch, or return None."""
    problems: list[str] = []
    _check(value, schema, "input", problems)
    if problems:
        raise ToolInputError("; ".join(problems))
