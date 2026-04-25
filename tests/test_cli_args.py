"""Tests for CLI argument formatting."""

from mori.protocols.cli.args import format_args


def test_flags_basic():
    result = format_args({"pattern": "TODO", "path": "."}, format="flags")
    assert result == ["--pattern", "TODO", "--path", "."]


def test_flags_boolean_true():
    result = format_args({"verbose": True}, format="flags")
    assert result == ["--verbose"]


def test_flags_boolean_false():
    result = format_args({"verbose": False}, format="flags")
    assert result == []


def test_flags_mixed():
    result = format_args({"pattern": "TODO", "verbose": True, "quiet": False}, format="flags")
    assert "--pattern" in result
    assert "TODO" in result
    assert "--verbose" in result
    assert "--quiet" not in result


def test_positional_basic():
    result = format_args({"0": "TODO", "1": "src/"}, format="positional")
    assert result == ["TODO", "src/"]


def test_positional_ordering():
    result = format_args({"2": "c", "0": "a", "1": "b"}, format="positional")
    assert result == ["a", "b", "c"]


def test_subcommand_basic():
    result = format_args({"action": "status"}, format="subcommand")
    assert result == ["status"]


def test_subcommand_with_flags():
    result = format_args({"action": "status", "short": True}, format="subcommand")
    assert result[0] == "status"
    assert "--short" in result


def test_subcommand_with_value_flags():
    result = format_args({"action": "log", "n": "5"}, format="subcommand")
    assert result[0] == "log"
    assert "--n" in result
    assert "5" in result


def test_empty_args():
    result = format_args({}, format="flags")
    assert result == []


def test_int_value_converted_to_string():
    result = format_args({"count": 5}, format="flags")
    assert result == ["--count", "5"]
