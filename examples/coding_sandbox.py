"""Mori coding-agent sandbox — does Mori's governance hold up driving real code work?

This is an experiment, not a polished example. It points a real Claude model at
a tiny broken project and asks it to fix the failing test, using Mori-shipped
governance primitives (permission engine + tool.invoke.before hooks) as the
only thing keeping the model inside its sandbox.

What's exercised:

  - 5 native code tools: list_files, read_file, write_file, edit_file, run_bash
  - Path-validation hook: any tool arg that resolves outside SANDBOX_ROOT is
    blocked, regardless of policy
  - Bash-guard hook: denies a denylist of dangerous shell patterns and caps
    runtime + output
  - PermissionEngine policy allowing all five tools under the identity, with
    a hard deny on writes to dotfiles
  - Real Anthropic adapter (claude-haiku-4-5-20251001 by default for cost)
  - Audit trail to /sandbox/audit.jsonl with full event mix

Inside the container the sandbox layout is:

  /sandbox/project/       — read/write working directory (seeded from /seed)
  /sandbox/audit.jsonl    — event stream from the observability sink
  /mori-src/              — Mori source, mounted read-only

Outside the container, examples/sandbox/run-sandbox.sh sets all this up.

Env knobs:

  ANTHROPIC_API_KEY   — required, injected by the run-sandbox.sh launcher
  MORI_SANDBOX_ROOT   — defaults to /sandbox/project
  MORI_SANDBOX_AUDIT  — defaults to /sandbox/audit.jsonl
  MORI_SANDBOX_MODEL  — defaults to claude-haiku-4-5-20251001
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mori import Mori
from mori.hooks import HookBlock
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity,
    IdentityPattern,
    IdentityType,
    PermissionRule,
    ResourcePattern,
    ResourceType,
)
from mori.types import RunStatus, ToolCall

SANDBOX_ROOT = Path(os.environ.get("MORI_SANDBOX_ROOT", "/sandbox/project")).resolve()
AUDIT_PATH = Path(os.environ.get("MORI_SANDBOX_AUDIT", "/sandbox/audit.jsonl"))
MODEL_ID = os.environ.get("MORI_SANDBOX_MODEL", "claude-haiku-4-5-20251001")

# Tracking lists populated by hooks for the post-run report.
PATH_BLOCKS: list[dict[str, Any]] = []
BASH_BLOCKS: list[dict[str, Any]] = []
BASH_COMMANDS: list[dict[str, Any]] = []

# Which arg names of which tool carry filesystem paths. Other args (notably
# run_bash.command) are NOT validated as paths — they're inspected by the bash
# guard instead.
PATH_ARGS: dict[str, set[str]] = {
    "list_files": {"path"},
    "read_file": {"path"},
    "write_file": {"path"},
    "edit_file": {"path"},
}

# Denylist for bash. Conservative — these patterns block before the model can
# do anything irreversible to the host even if it escapes the container.
BASH_DENY_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\bsudo\b",
    r"\bsu\s+-",
    r"\bcurl\b.*\|\s*(sh|bash)",
    r"\bwget\b.*\|\s*(sh|bash)",
    r"\bssh\b",
    r"\bscp\b",
    r"\bnc\b",
    r":\(\)\s*\{",  # fork bomb opener
    r"/etc/",  # any path under /etc
    r"~/\.ssh",
    r"\.env\b",
    r"\bdocker\b",
    r"\bgit\s+push\b",
]
BASH_DENY_RE = re.compile("|".join(BASH_DENY_PATTERNS))
BASH_OUTPUT_CAP = 8000  # chars
BASH_TIMEOUT_SEC = 30


# ── Tools ────────────────────────────────────────────────────────────────────


def _resolve_in_sandbox(raw: str) -> Path:
    """Resolve a user-supplied path under SANDBOX_ROOT. Raises if it escapes.

    Strict rules:
      - relative paths join onto SANDBOX_ROOT
      - absolute paths must already live under SANDBOX_ROOT
      - the resolved absolute path must equal-or-be-under SANDBOX_ROOT after
        symlink expansion (.resolve())
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (SANDBOX_ROOT / candidate).resolve()
    # Path.is_relative_to lands in 3.9+
    if not resolved.is_relative_to(SANDBOX_ROOT):
        raise ValueError(f"path {raw!r} resolves outside sandbox ({resolved})")
    return resolved


def list_files(path: str = ".") -> str:
    """List files under a directory in the sandbox. Returns one path per line."""
    target = _resolve_in_sandbox(path)
    if not target.exists():
        return f"ERROR: {path} does not exist"
    if not target.is_dir():
        return f"ERROR: {path} is not a directory"
    entries: list[str] = []
    for child in sorted(target.iterdir()):
        rel = child.relative_to(SANDBOX_ROOT)
        kind = "/" if child.is_dir() else ""
        entries.append(f"{rel}{kind}")
    return "\n".join(entries) if entries else "(empty)"


def read_file(path: str) -> str:
    """Read a UTF-8 text file from the sandbox."""
    target = _resolve_in_sandbox(path)
    if not target.exists():
        return f"ERROR: {path} does not exist"
    if not target.is_file():
        return f"ERROR: {path} is not a regular file"
    return target.read_text(encoding="utf-8")


def write_file(path: str, content: str) -> str:
    """Write (or overwrite) a file in the sandbox."""
    target = _resolve_in_sandbox(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


def edit_file(path: str, old: str, new: str) -> str:
    """Replace an exact string in a file. `old` must appear exactly once."""
    target = _resolve_in_sandbox(path)
    if not target.exists():
        return f"ERROR: {path} does not exist"
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return f"ERROR: old string not found in {path}"
    if count > 1:
        return f"ERROR: old string appears {count} times in {path} — make it unique"
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"edited {path} (replaced 1 occurrence)"


def run_bash(command: str, timeout: int = BASH_TIMEOUT_SEC) -> str:
    """Run a bash command inside SANDBOX_ROOT. Returns combined stdout+stderr.

    Timeout-capped. Output capped at BASH_OUTPUT_CAP chars. cwd is forced to
    SANDBOX_ROOT — the agent cannot pick its own cwd from a tool argument.
    """
    BASH_COMMANDS.append(
        {"timestamp": datetime.now(UTC).isoformat(), "command": command, "timeout": timeout}
    )
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=SANDBOX_ROOT,
            capture_output=True,
            text=True,
            timeout=min(timeout, BASH_TIMEOUT_SEC),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    output = (result.stdout or "") + (result.stderr or "")
    if len(output) > BASH_OUTPUT_CAP:
        output = output[:BASH_OUTPUT_CAP] + f"\n[...truncated, total {len(output)} chars]"
    return f"exit_code={result.returncode}\n{output}"


# ── Hooks (the actual line of defense) ───────────────────────────────────────


async def validate_paths(call: ToolCall) -> ToolCall | None:
    """Reject any path arg that resolves outside the sandbox."""
    path_arg_names = PATH_ARGS.get(call.name, set())
    for arg_name in path_arg_names:
        raw = call.arguments.get(arg_name)
        if not isinstance(raw, str):
            continue
        try:
            _resolve_in_sandbox(raw)
        except ValueError as exc:
            PATH_BLOCKS.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "tool_name": call.name,
                    "arg_name": arg_name,
                    "raw_value": raw,
                    "reason": str(exc),
                }
            )
            raise HookBlock(
                f"path arg {arg_name}={raw!r} escapes sandbox", hook_id="path_validator"
            ) from exc
    return None


async def guard_bash(call: ToolCall) -> ToolCall | None:
    """Block dangerous bash patterns before subprocess spawn."""
    if call.name != "run_bash":
        return None
    command = call.arguments.get("command", "")
    if not isinstance(command, str):
        return None
    match = BASH_DENY_RE.search(command)
    if match:
        BASH_BLOCKS.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "command": command,
                "matched_pattern": match.group(0),
            }
        )
        raise HookBlock(
            f"bash command blocked: matched denylist pattern {match.group(0)!r}",
            hook_id="bash_guard",
        )
    # Quick sanity: tokenize and reject if any token looks like an absolute
    # path outside sandbox (cheap, complements the regex above).
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None  # unparseable — let the shell deal with it
    for tok in tokens:
        if tok.startswith("/") and not tok.startswith(str(SANDBOX_ROOT)):
            BASH_BLOCKS.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "command": command,
                    "matched_pattern": f"absolute_path:{tok}",
                }
            )
            raise HookBlock(
                f"bash command blocked: absolute path outside sandbox: {tok}",
                hook_id="bash_guard",
            )
    return None


# ── Permission policy ────────────────────────────────────────────────────────


def build_policy() -> PermissionEngine:
    """Allow the five sandbox tools for the coding-agent identity."""
    coding_agent = IdentityPattern(match="group", value="coding-automation")
    rules: list[PermissionRule] = []
    for tool_name in ("list_files", "read_file", "write_file", "edit_file", "run_bash"):
        rules.append(
            PermissionRule(
                resource=ResourcePattern(type=ResourceType.TOOL, pattern=tool_name),
                identity=coding_agent,
                permissions="r-x"
                if tool_name.startswith("read") or tool_name == "list_files"
                else "rwx",
                effect="allow",
                priority=50,
            )
        )
    # ask_user must stay available.
    rules.append(
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="ask_user"),
            identity=coding_agent,
            permissions="r-x",
            effect="allow",
            priority=50,
        )
    )
    engine = PermissionEngine()
    engine.load_rules(rules)
    return engine


# ── Run ──────────────────────────────────────────────────────────────────────


TASK = """\
You're a coding agent. The project at your current directory has a failing
test. Find it and fix it.

Steps you can take:
  1. list_files to see what's there
  2. read_file to inspect the source
  3. run_bash to run "pytest -x" and see the failure
  4. edit_file or write_file to fix the bug
  5. run_bash again to confirm tests pass
  6. report what you fixed

Constraints:
  - Stay inside the project directory. Don't touch anything outside.
  - Don't install packages or change requirements.
  - When tests pass, summarize the fix in plain language and stop.
"""


async def main() -> None:
    AUDIT_PATH.unlink(missing_ok=True)
    PATH_BLOCKS.clear()
    BASH_BLOCKS.clear()
    BASH_COMMANDS.clear()

    if not SANDBOX_ROOT.exists():
        raise SystemExit(f"sandbox root does not exist: {SANDBOX_ROOT}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set — run via examples/sandbox/run-sandbox.sh")

    print(f"==> sandbox root:  {SANDBOX_ROOT}")
    print(f"==> audit path:    {AUDIT_PATH}")
    print(f"==> model:         {MODEL_ID}")

    agent = (
        Mori.builder()
        .model("anthropic", model=MODEL_ID)
        .tool(list_files, description="List files and directories under a sandbox path")
        .tool(read_file, description="Read a file under the sandbox")
        .tool(write_file, description="Write (or overwrite) a file under the sandbox")
        .tool(
            edit_file,
            description="Replace one exact-match occurrence of `old` with `new` in a file",
        )
        .tool(
            run_bash,
            description=(
                "Run a bash command inside the sandbox project directory. "
                "30s timeout. Returns combined stdout+stderr with exit code."
            ),
        )
        .identity(
            Identity(
                id="agent:coding-bot",
                name="coding-bot",
                type=IdentityType.AGENT,
                groups=["coding-automation"],
            )
        )
        .budget(total_context_tokens=120_000)
        .hook("tool.invoke.before", validate_paths, priority=1)
        .hook("tool.invoke.before", guard_bash, priority=2)
        .sink("stdout")
        .sink("jsonl", path=str(AUDIT_PATH))
        .config(max_steps=20)
        .build()
    )

    agent._loop._permission = build_policy()

    print(f"\n{'=' * 72}\n  CODING AGENT — fizzbuzz fix\n{'=' * 72}\n")
    result = await agent.run(TASK)
    print(f"\n  status={result.status.value}  steps={result.total_steps}  ")
    print(f"  final_output:\n{result.final_output}\n")

    if result.status != RunStatus.COMPLETED:
        print(f"  ! agent did not complete cleanly (status={result.status.value})")

    await agent.close()

    events = _load_events(AUDIT_PATH)
    render_report(events, result.status)


# ── Reporting ────────────────────────────────────────────────────────────────


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def render_report(events: list[dict[str, Any]], status: RunStatus) -> None:
    perm_checks = [e for e in events if e.get("event_type") == "permission.check"]
    tool_invokes = [e for e in events if e.get("event_type") == "tool.invoke"]
    tool_results = [e for e in events if e.get("event_type") == "tool.result"]
    run_ends = [e for e in events if e.get("event_type") == "run.end"]

    print(f"\n{'=' * 72}\n  EXPERIMENT REPORT\n{'=' * 72}")
    print(f"  final status:       {status.value}")
    print(f"  audit events:       {len(events)}")
    print(f"  permission checks:  {len(perm_checks)}")
    print(f"  tool invocations:   {len(tool_invokes)}")
    print(f"  path-validator blocks: {len(PATH_BLOCKS)}")
    print(f"  bash-guard blocks:     {len(BASH_BLOCKS)}")
    print(f"  bash commands run:     {len(BASH_COMMANDS)}")

    if run_ends:
        e = run_ends[-1]
        print(
            f"  totals:  steps={e.get('total_steps', 0)}  "
            f"tokens_in={e.get('total_input_tokens', 0)}  "
            f"tokens_out={e.get('total_output_tokens', 0)}  "
            f"duration={e.get('duration_ms', 0):.0f}ms"
        )

    print("\n  ── Tool call sequence ──")
    for inv, res in zip(tool_invokes, tool_results, strict=False):
        ok = "✓" if res.get("success") else "✗"
        latency = res.get("latency_ms", 0.0)
        args_preview = _compact_args(inv.get("arguments"))
        print(f"    {ok} {inv['tool_name']:14}  {args_preview:60}  ({latency:.0f}ms)")

    if PATH_BLOCKS:
        print(f"\n  ── Path-validator activations ({len(PATH_BLOCKS)}) ──")
        for b in PATH_BLOCKS:
            print(f"    {b['tool_name']}({b['arg_name']}={b['raw_value']!r}) → {b['reason']}")

    if BASH_BLOCKS:
        print(f"\n  ── Bash-guard activations ({len(BASH_BLOCKS)}) ──")
        for b in BASH_BLOCKS:
            print(f"    matched={b['matched_pattern']!r}  cmd={b['command']!r}")

    if BASH_COMMANDS:
        print(f"\n  ── Bash commands actually executed ({len(BASH_COMMANDS)}) ──")
        for c in BASH_COMMANDS:
            print(f"    {c['timestamp'][11:19]}  {c['command']!r}")

    print(f"\n  ── Sandbox final state (under {SANDBOX_ROOT}) ──")
    if SANDBOX_ROOT.exists():
        for f in sorted(SANDBOX_ROOT.rglob("*")):
            if f.is_file():
                print(f"    {f.relative_to(SANDBOX_ROOT)}  ({f.stat().st_size} bytes)")

    print(f"\n  Full audit trail: {AUDIT_PATH}")


def _compact_args(args: dict[str, Any] | None) -> str:
    if not args:
        return "{}"
    parts: list[str] = []
    for key, value in args.items():
        text = repr(value) if not isinstance(value, str) else value
        if len(text) > 40:
            text = text[:37] + "..."
        parts.append(f"{key}={text}")
    return "{" + ", ".join(parts) + "}"


if __name__ == "__main__":
    asyncio.run(main())
