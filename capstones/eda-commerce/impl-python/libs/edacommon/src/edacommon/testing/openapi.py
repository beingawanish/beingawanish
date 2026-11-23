"""Validate HTTP responses against the OpenAPI documents in contracts/openapi (checklist §11).

Resolves the relative ``./common.yaml#/...`` references with ``referencing`` and validates a
response body with JSON Schema 2020-12 (OpenAPI 3.1 schemas are JSON Schema).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def openapi_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "contracts" / "openapi"
        if cand.is_dir():
            return cand
    raise FileNotFoundError("contracts/openapi not found")


@cache
def _registry() -> Registry:
    resources = []
    for p in openapi_dir().glob("*.yaml"):
        doc = yaml.safe_load(p.read_text())
        resources.append((p.name, Resource.from_contents(doc, default_specification=_spec())))
        resources.append((f"./{p.name}", Resource.from_contents(doc, default_specification=_spec())))
    return Registry().with_resources(resources)


def _spec() -> Any:
    from referencing.jsonschema import DRAFT202012

    return DRAFT202012


@cache
def _doc(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((openapi_dir() / name).read_text())
    return doc


def response_schema(doc: str, path: str, method: str, status: int) -> dict[str, Any] | None:
    op = _doc(doc)["paths"][path][method.lower()]
    resp = op["responses"].get(str(status))
    if resp is None:
        raise AssertionError(f"{doc} {method} {path} does not declare status {status}")
    if "$ref" in resp:
        target, frag = resp["$ref"].split("#")
        resolved = _doc(Path(target).name if target else doc)
        for part in frag.strip("/").split("/"):
            resolved = resolved[part]
        resp = resolved
    content = resp.get("content")
    if not content:
        return None
    media = content.get("application/json") or content.get("application/problem+json")
    return media.get("schema") if media else None


def validate_response(doc: str, path: str, method: str, status: int, body: Any) -> None:
    schema = response_schema(doc, path, method, status)
    if schema is None:
        return
    # Anchor the schema inside its document so relative refs ('#/components/...') resolve.
    wrapper = {"$ref": f"{doc}#/__probe__"}
    full = dict(_doc(doc))
    full["__probe__"] = schema
    registry = _registry().with_resource(doc, Resource.from_contents(full, default_specification=_spec()))
    validator = Draft202012Validator(wrapper, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(body), key=lambda e: e.path)
    if errors:
        raise AssertionError(
            f"{method} {path} {status} violates {doc}: " + "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        )
