"""Mixed tools example — Python functions + file tools in one agent.

Shows native computation tools and file tools working together.
The agent picks the right tool for each sub-task.

Requires: ANTHROPIC_API_KEY

Usage:
    cd ~/Projects/Mori
    python examples/mixed_tools.py
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from mori import Mori

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


# ── Computation tools ────────────────────────────────────────

def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


def divide(a: float, b: float) -> str:
    """Divide a by b."""
    if b == 0:
        return "Error: division by zero"
    return str(a / b)


def calculate(operation: str, numbers: list[float]) -> str:
    """Perform a math operation on a list of numbers.

    operation: one of 'sum', 'average', 'min', 'max', 'count'
    numbers: list of numbers to operate on
    """
    if not numbers:
        return "Error: provide at least one number"
    op = operation.lower()
    if op == "sum":
        return str(sum(numbers))
    elif op == "average":
        return str(sum(numbers) / len(numbers))
    elif op == "min":
        return str(min(numbers))
    elif op == "max":
        return str(max(numbers))
    elif op == "count":
        return str(len(numbers))
    else:
        return f"Error: unknown operation '{op}'. Supported: sum, average, min, max, count"


# ── File tools ───────────────────────────────────────────────

def list_files(directory: str = ".") -> str:
    """List files in a directory with line counts."""
    full_path = Path(PROJECT_ROOT) / directory
    if not full_path.is_dir():
        return f"Error: not a directory: {directory}"
    results = []
    for f in sorted(full_path.rglob("*.py")):
        rel = f.relative_to(Path(PROJECT_ROOT))
        lines = len(f.read_text().splitlines())
        results.append(f"{rel}: {lines} lines")
    return "\n".join(results) or "No Python files found."


def read_file(path: str) -> str:
    """Read the contents of a file."""
    full_path = Path(PROJECT_ROOT) / path
    if not full_path.exists():
        return f"Error: file not found: {path}"
    return full_path.read_text()


def format_table(headers: str, rows: str) -> str:
    """Format data as an aligned text table.

    headers: comma-separated column names
    rows: semicolon-separated rows, each with comma-separated values
    """
    cols = [h.strip() for h in headers.split(",")]
    data = [[v.strip() for v in row.split(",")] for row in rows.split(";")]

    widths = [max(len(c), *(len(r[i]) if i < len(r) else 0 for r in data)) for i, c in enumerate(cols)]
    header_line = " | ".join(c.ljust(w) for c, w in zip(cols, widths))
    sep = "-+-".join("-" * w for w in widths)
    body = "\n".join(
        " | ".join((r[i] if i < len(r) else "").ljust(w) for i, w in enumerate(widths))
        for r in data
    )
    return f"{header_line}\n{sep}\n{body}"


# ── Agent ────────────────────────────────────────────────────

async def main():
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(add, description="Add two numbers")
        .tool(subtract, description="Subtract b from a")
        .tool(multiply, description="Multiply two numbers")
        .tool(divide, description="Divide a by b")
        .tool(calculate, description="Calculate over a list of numbers: sum, average, min, max, count")
        .tool(list_files, description="List Python files in a directory with line counts")
        .tool(read_file, description="Read the contents of a file")
        .tool(format_table, description="Format data as an aligned text table")
        .sink("stdout")
        .config(max_steps=15)
        .build()
    )

    task = (
        "Look at the Python files in the mori/ directory, count the total lines "
        "of code across all .py files, then calculate the average lines per file. "
        "Present the results in a table."
    )

    print(f"{'━' * 70}")
    print(f"  Task: {task}")
    print(f"{'━' * 70}\n")

    result = await agent.run(task)

    print(f"\n{'━' * 70}")
    print(f"  Answer:\n")
    print(f"  {result.final_output}")
    print(f"\n  [{result.total_steps} steps, {result.total_tool_calls} tool calls, "
          f"{result.total_usage.total} tokens]")
    print(f"{'━' * 70}")

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
