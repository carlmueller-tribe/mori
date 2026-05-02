"""CLI tools example — shell commands as agent tools.

Shows how to register CLI programs (grep, find, cat, wc) as tools
that the agent can call just like Python functions.

Requires: ANTHROPIC_API_KEY

Usage:
    cd ~/Projects/Mori
    python examples/cli_tools.py
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from mori import Mori

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


async def main():
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        # Raw format — model writes the full command args naturally
        .cli(
            "grep",
            command="grep",
            description=(
                "Search for text in files. Provide the full arguments as a command string. "
                "Examples: '-rn TODO mori/', '-rl import tests/', '--include=*.py -rn def mori/'"
            ),
            args_format="raw",
            args_schema={
                "command": {"type": "string", "description": "Full argument string for grep"},
            },
            timeout_sec=10.0,
            cwd=PROJECT_ROOT,
        )
        .cli(
            "find",
            command="find",
            description=(
                "Find files. Provide the full arguments as a command string. "
                "Examples: 'mori/ -name *.py -type f', '. -name *.md'"
            ),
            args_format="raw",
            args_schema={
                "command": {"type": "string", "description": "Full argument string for find"},
            },
            cwd=PROJECT_ROOT,
        )
        .cli(
            "cat",
            command="cat",
            description="Read the contents of a file. Example: 'pyproject.toml'",
            args_format="raw",
            args_schema={"command": {"type": "string", "description": "File path to read"}},
            cwd=PROJECT_ROOT,
        )
        .cli(
            "wc",
            command="wc",
            description="Count lines/words/bytes. Example: '-l mori/types.py'",
            args_format="raw",
            args_schema={"command": {"type": "string", "description": "Flags and file path"}},
            cwd=PROJECT_ROOT,
        )
        # Structured format — works well for subcommand-style tools
        .cli(
            "git",
            command="git",
            description="Run git commands. 'action' is the subcommand (log, status, diff, show, etc.)",
            args_format="subcommand",
            args_schema={
                "action": {
                    "type": "string",
                    "description": "Git subcommand (log, status, diff, show, blame, etc.)",
                },
                "oneline": {"type": "boolean", "description": "One line per commit (for log)"},
                "n": {"type": "string", "description": "Number of commits to show"},
                "stat": {"type": "boolean", "description": "Show diffstat"},
            },
            cwd=PROJECT_ROOT,
        )
        .sink("stdout")
        .config(max_steps=10)
        .build()
    )

    tasks = [
        "How many Python files are in the mori/ directory? List them.",
        "Find all TODO comments in the codebase and tell me what they say.",
        "Read the pyproject.toml and tell me what version of Mori is defined.",
        "Show me the last 5 git commits with stats.",
    ]

    for task in tasks:
        print(f"\n{'━' * 70}")
        print(f"  Task: {task}")
        print(f"{'━' * 70}")

        result = await agent.run(task)

        print(f"\n  Answer: {result.final_output}")
        print(
            f"  [{result.total_steps} steps, {result.total_tool_calls} tool calls, "
            f"{result.total_usage.total} tokens]"
        )

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
