"""Infer JSON Schema from Python function type annotations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_args, get_origin

from pydantic import BaseModel

_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a single type annotation to a JSON Schema fragment."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return {"type": "string"}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        schema = annotation.model_json_schema()
        schema.pop("title", None)
        return schema

    if annotation in _TYPE_MAP:
        return {"type": _TYPE_MAP[annotation]}

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is list:
        item_schema = _annotation_to_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item_schema}

    if origin is dict:
        return {"type": "object"}

    return {"type": "string"}


def infer_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Infer a JSON Schema for a callable's input parameters.

    Skips 'self', 'cls', and 'return'. Parameters without annotations
    default to {"type": "string"}.
    """
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        annotation = param.annotation
        properties[name] = _annotation_to_schema(annotation)

        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema
