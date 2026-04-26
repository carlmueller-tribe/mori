"""Tests for CLIRunner — uses real subprocesses."""

import pytest

from mori.protocols.cli.runner import CLIRunner, CLIToolConfig


@pytest.fixture
def runner():
    return CLIRunner()


async def test_run_echo(runner):
    config = CLIToolConfig(command="echo", args_format="positional")
    result = await runner.run(arguments={"0": "hello world"}, config=config)
    assert result.success is True
    assert "hello world" in result.content


async def test_run_flags_format(runner):
    config = CLIToolConfig(command="echo", args_format="flags")
    result = await runner.run(arguments={"n": "test"}, config=config)
    assert result.success is True


async def test_run_exit_code_nonzero(runner):
    config = CLIToolConfig(command="false")
    result = await runner.run(arguments={}, config=config)
    assert result.success is False


async def test_run_timeout(runner):
    config = CLIToolConfig(command="sleep", args_format="positional", timeout_sec=0.1)
    result = await runner.run(arguments={"0": "10"}, config=config)
    assert result.success is False
    assert "timed out" in (result.error or "").lower()


async def test_run_captures_stderr(runner):
    config = CLIToolConfig(command="sh", args_format="positional")
    result = await runner.run(
        arguments={"0": "-c", "1": "echo err >&2; exit 1"},
        config=config,
    )
    assert result.success is False
    assert "err" in (result.error or "") or "err" in result.metadata.get("stderr", "")


async def test_run_output_cap(runner):
    config = CLIToolConfig(
        command="python3",
        args_format="positional",
        max_output_bytes=50,
    )
    result = await runner.run(
        arguments={"0": "-c", "1": "print('x' * 200)"},
        config=config,
    )
    assert result.success is True
    assert len(result.content.encode()) <= 60  # Small overhead allowed


async def test_run_with_cwd(runner, tmp_path):
    config = CLIToolConfig(command="pwd", cwd=str(tmp_path))
    result = await runner.run(arguments={}, config=config)
    assert result.success is True
    assert str(tmp_path) in result.content


async def test_run_with_env(runner):
    config = CLIToolConfig(
        command="sh",
        args_format="positional",
        env={"MORI_TEST_VAR": "hello123"},
    )
    result = await runner.run(
        arguments={"0": "-c", "1": "echo $MORI_TEST_VAR"},
        config=config,
    )
    assert result.success is True
    assert "hello123" in result.content


async def test_run_latency_tracked(runner):
    config = CLIToolConfig(command="echo", args_format="positional")
    result = await runner.run(arguments={"0": "hi"}, config=config)
    assert result.latency_ms > 0


async def test_run_raw_format(runner):
    """Raw format — model provides the full command args as a string."""
    config = CLIToolConfig(command="echo", args_format="raw")
    result = await runner.run(arguments={"command": "-n hello raw"}, config=config)
    assert result.success is True
    assert "hello raw" in result.content


async def test_run_raw_grep(runner, tmp_path):
    """Raw format with grep — realistic usage."""
    test_file = tmp_path / "test.py"
    test_file.write_text("# TODO: fix this\nprint('hello')\n# TODO: add tests\n")
    config = CLIToolConfig(command="grep", args_format="raw", cwd=str(tmp_path))
    result = await runner.run(arguments={"command": "-n TODO test.py"}, config=config)
    assert result.success is True
    assert "TODO" in result.content
    assert "1:" in result.content  # line number
