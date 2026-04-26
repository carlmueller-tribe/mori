"""Format tool arguments into command-line argument lists."""

from __future__ import annotations

from typing import Any, Literal


def format_args(
    arguments: dict[str, Any],
    format: Literal["flags", "positional", "subcommand", "raw"],
) -> list[str]:
    if format == "flags":
        return _format_flags(arguments)
    elif format == "positional":
        return _format_positional(arguments)
    elif format == "subcommand":
        return _format_subcommand(arguments)
    elif format == "raw":
        return _format_raw(arguments)
    else:
        raise ValueError(f"Unknown format: {format}")


def _flag_prefix(key: str) -> str:
    """Single-char keys get '-', multi-char get '--'."""
    return f"-{key}" if len(key) == 1 else f"--{key}"


def _format_flags(arguments: dict[str, Any]) -> list[str]:
    """Format as flags. Keys starting with '_' are bare trailing positional args."""
    flags: list[str] = []
    trailing: list[str] = []
    for key, value in arguments.items():
        if key.startswith("_"):
            # Bare positional arg — appended at the end without a flag prefix
            trailing.append(str(value))
        elif isinstance(value, bool):
            if value:
                flags.append(_flag_prefix(key))
        else:
            flags.append(_flag_prefix(key))
            flags.append(str(value))
    return flags + trailing


def _format_positional(arguments: dict[str, Any]) -> list[str]:
    sorted_keys = sorted(arguments.keys(), key=lambda k: int(k))
    return [str(arguments[k]) for k in sorted_keys]


def _format_raw(arguments: dict[str, Any]) -> list[str]:
    """Raw command string — the model provides the full args as a single string.

    Expects {"command": "grep -rn TODO mori/"}.
    Returns the string split by shell rules.
    """
    import shlex

    command = arguments.get("command", "")
    if not command:
        return []
    return shlex.split(str(command))


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
                result.append(_flag_prefix(key))
        else:
            result.append(_flag_prefix(key))
            result.append(str(value))
    return result
