"""CLIRunner — execute CLI tools as subprocesses."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Literal

import anyio

from mori.protocols.cli.args import format_args
from mori.types import MoriModel, ToolResult


class CLIToolConfig(MoriModel):
    command: str
    args_format: Literal["positional", "flags", "subcommand", "raw"] = "flags"
    shell: bool = False
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout_sec: float = 60.0
    max_output_bytes: int = 1_048_576
    capture_stderr: bool = True


class CLIRunner:
    """Execute CLI tools as subprocesses."""

    async def run(
        self,
        arguments: dict[str, Any],
        config: CLIToolConfig,
    ) -> ToolResult:
        args_list = format_args(arguments, format=config.args_format)
        cmd = [config.command] + args_list

        env: dict[str, str] | None = None
        if config.env:
            env = {**os.environ, **config.env}

        start = time.monotonic()
        try:
            with anyio.fail_after(config.timeout_sec):
                result = await anyio.run_process(
                    cmd,
                    cwd=config.cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.PIPE if config.capture_stderr else None,
                    check=False,
                )

            elapsed_ms = (time.monotonic() - start) * 1000
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

            if len(stdout.encode()) > config.max_output_bytes:
                stdout = stdout.encode()[:config.max_output_bytes].decode("utf-8", errors="replace")

            if result.returncode == 0:
                return ToolResult(
                    tool_name=config.command,
                    call_id="",
                    success=True,
                    content=stdout.strip(),
                    latency_ms=elapsed_ms,
                    metadata={"stderr": stderr, "exit_code": result.returncode},
                )
            else:
                return ToolResult(
                    tool_name=config.command,
                    call_id="",
                    success=False,
                    content=stdout.strip(),
                    error=stderr.strip() or f"Exit code {result.returncode}",
                    latency_ms=elapsed_ms,
                    metadata={"stderr": stderr, "exit_code": result.returncode},
                )

        except TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=config.command,
                call_id="",
                success=False,
                content="",
                error=f"Process timed out after {config.timeout_sec}s",
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=config.command,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )
