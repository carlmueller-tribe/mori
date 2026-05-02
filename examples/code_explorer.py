"""Code explorer example — an agent that navigates a codebase.

Uses .cli() with raw and subcommand formats to give the agent
shell access for code exploration. No native Python wrappers needed.

Requires: ANTHROPIC_API_KEY

Usage:
    cd ~/Projects/Mori
    python examples/code_explorer.py
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from mori import Mori

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
TRACES_PATH = str(Path(PROJECT_ROOT) / "explorer_traces.jsonl")


async def main():
    Path(TRACES_PATH).unlink(missing_ok=True)

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        # Raw CLI tools — model writes natural command args
        .cli(
            "grep",
            command="grep",
            description="Search for text in files. Examples: '-rn TODO mori/', '--include=*.py -rn class .'",
            args_format="raw",
            args_schema={"command": {"type": "string", "description": "Arguments for grep"}},
            timeout_sec=10.0,
            cwd=PROJECT_ROOT,
        )
        .cli(
            "find",
            command="find",
            description="Find files. Examples: 'mori/ -name *.py -type f', '. -name *.md'",
            args_format="raw",
            args_schema={"command": {"type": "string", "description": "Arguments for find"}},
            cwd=PROJECT_ROOT,
        )
        .cli(
            "cat",
            command="cat",
            description="Read file contents. Example: 'pyproject.toml', 'mori/agent.py'",
            args_format="raw",
            args_schema={"command": {"type": "string", "description": "File path to read"}},
            cwd=PROJECT_ROOT,
        )
        .cli(
            "wc",
            command="wc",
            description="Count lines/words/bytes. Examples: '-l tests/*.py', '-l mori/types.py'",
            args_format="raw",
            args_schema={
                "command": {"type": "string", "description": "Flags and file paths for wc"}
            },
            cwd=PROJECT_ROOT,
        )
        .cli(
            "head",
            command="head",
            description="Show first N lines of a file. Example: '-20 mori/agent.py'",
            args_format="raw",
            args_schema={
                "command": {"type": "string", "description": "Flags and file path for head"}
            },
            cwd=PROJECT_ROOT,
        )
        # Structured CLI tool — subcommand format fits git perfectly
        .cli(
            "git",
            command="git",
            description="Run git commands. 'action' is the subcommand.",
            args_format="subcommand",
            args_schema={
                "action": {
                    "type": "string",
                    "description": "Git subcommand (log, status, diff, show, blame)",
                },
                "oneline": {"type": "boolean", "description": "One line per commit"},
                "stat": {"type": "boolean", "description": "Show diffstat"},
                "n": {"type": "string", "description": "Number of commits"},
            },
            cwd=PROJECT_ROOT,
        )
        .sink("stdout")
        .sink("jsonl", path=TRACES_PATH)
        .config(max_steps=15)
        .build()
    )

    questions = [
        "What public classes does mori/agent.py export? Describe each in one sentence.",
        "How many test files are there and what's the total line count across all of them?",
        "What was the most recent git commit message?",
    ]

    for question in questions:
        print(f"\n{'━' * 70}")
        print(f"  Q: {question}")
        print(f"{'━' * 70}\n")

        result = await agent.run(question)

        print(f"\n  A: {result.final_output}")
        print(
            f"  [{result.total_steps} steps, {result.total_tool_calls} tool calls, "
            f"{result.total_usage.total} tokens]\n"
        )

    await agent.close()

    # ── Summary from traces ──────────────────────────────────
    lines = Path(TRACES_PATH).read_text().strip().split("\n")
    events = [json.loads(line) for line in lines]
    tool_events = [e for e in events if e["event_type"] == "tool.invoke"]

    print(f"{'━' * 70}")
    print("  Session Summary (from explorer_traces.jsonl)")
    print(f"{'━' * 70}")
    print(f"  Total events: {len(events)}")
    print(f"  Total tool invocations: {len(tool_events)}")

    tool_counts: dict[str, int] = {}
    for e in tool_events:
        name = e["tool_name"]
        tool_counts[name] = tool_counts.get(name, 0) + 1
    for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        print(f"    {name}: {count} calls")


if __name__ == "__main__":
    asyncio.run(main())
