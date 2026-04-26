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
    assert "-n" in result
    assert "5" in result


def test_empty_args():
    result = format_args({}, format="flags")
    assert result == []


def test_int_value_converted_to_string():
    result = format_args({"count": 5}, format="flags")
    assert result == ["--count", "5"]


def test_single_char_flag_uses_single_dash():
    result = format_args({"r": True, "n": True}, format="flags")
    assert "-r" in result
    assert "-n" in result
    assert "--r" not in result
    assert "--n" not in result


def test_single_char_value_flag():
    result = format_args({"e": "pattern"}, format="flags")
    assert result == ["-e", "pattern"]


def test_mixed_short_and_long_flags():
    result = format_args({"r": True, "include": "*.py", "n": True}, format="flags")
    assert "-r" in result
    assert "-n" in result
    assert "--include" in result
    assert "*.py" in result


def test_underscore_keys_are_trailing_positional():
    """Keys starting with _ are bare trailing args, not flags."""
    result = format_args({"r": True, "e": "TODO", "_path": "."}, format="flags")
    assert result == ["-r", "-e", "TODO", "."]


def test_trailing_positional_after_all_flags():
    result = format_args({"n": True, "e": "hello", "_dir": "src/"}, format="flags")
    assert result[-1] == "src/"
    assert "-n" in result
    assert "-e" in result


def test_grep_realistic():
    """Realistic grep invocation: grep -rn -e TODO --include '*.py' ."""
    result = format_args(
        {"r": True, "n": True, "e": "TODO", "include": "*.py", "_path": "."},
        format="flags",
    )
    assert "-r" in result
    assert "-n" in result
    assert "-e" in result
    assert "TODO" in result
    assert "--include" in result
    assert "*.py" in result
    assert result[-1] == "."  # trailing positional at the end


# ── Raw format ───────────────────────────────────────────────

def test_raw_basic():
    result = format_args({"command": "grep -rn TODO mori/"}, format="raw")
    assert result == ["grep", "-rn", "TODO", "mori/"]


def test_raw_with_quotes():
    result = format_args({"command": "grep -r 'hello world' src/"}, format="raw")
    assert result == ["grep", "-r", "hello world", "src/"]


def test_raw_empty():
    result = format_args({"command": ""}, format="raw")
    assert result == []


def test_raw_complex_pipeline_args():
    result = format_args({"command": "find . -name '*.py' -type f"}, format="raw")
    assert result == ["find", ".", "-name", "*.py", "-type", "f"]
