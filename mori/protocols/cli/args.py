"""Format tool arguments into command-line argument lists."""

from __future__ import annotations

from typing import Any, Literal


def format_args(
    arguments: dict[str, Any],
    format: Literal["flags", "positional", "subcommand"],
) -> list[str]:
    if format == "flags":
        return _format_flags(arguments)
    elif format == "positional":
        return _format_positional(arguments)
    elif format == "subcommand":
        return _format_subcommand(arguments)
    else:
        raise ValueError(f"Unknown format: {format}")


def _format_flags(arguments: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, bool):
            if value:
                result.append(f"--{key}")
        else:
            result.append(f"--{key}")
            result.append(str(value))
    return result


def _format_positional(arguments: dict[str, Any]) -> list[str]:
    sorted_keys = sorted(arguments.keys(), key=lambda k: int(k))
    return [str(arguments[k]) for k in sorted_keys]


def _format_subcommand(arguments: dict[str, Any]) -> list[str]:
    result: list[str] = []
    action = arguments.get("action")
    if action:
        result.append(str(action))
    for key, value in arguments.items():
        if key == "action":
            continue
        if isinstance(value, bool):
            if value:
                result.append(f"--{key}")
        else:
            result.append(f"--{key}")
            result.append(str(value))
    return result
