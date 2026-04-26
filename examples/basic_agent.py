"""Basic Mori agent example — tool-calling with Claude.

Requires: ANTHROPIC_API_KEY environment variable.

Usage:
    python examples/basic_agent.py
"""

import asyncio
import random

from dotenv import load_dotenv

load_dotenv()

from mori import Mori


# ── Tools ────────────────────────────────────────────────────

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def roll_dice(sides: int = 6) -> int:
    """Roll a die with the given number of sides."""
    return random.randint(1, sides)


def lookup_price(item: str) -> str:
    """Look up the price of an item."""
    prices = {
        "coffee": 4.50,
        "sandwich": 8.99,
        "salad": 7.25,
        "water": 1.50,
    }
    price = prices.get(item.lower())
    if price is None:
        return f"Item '{item}' not found. Available: {', '.join(prices.keys())}"
    return f"{item}: ${price:.2f}"


# ── Agent ────────────────────────────────────────────────────

async def main():
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(add, description="Add two numbers")
        .tool(multiply, description="Multiply two numbers")
        .tool(roll_dice, description="Roll a die with N sides (default 6)")
        .tool(lookup_price, description="Look up the price of a menu item")
        .sink("stdout")
        .config(max_steps=10)
        .build()
    )

    tasks = [
        "What is (12 + 8) * 3?",
        "Roll two 20-sided dice and tell me the sum.",
        "How much would 2 coffees and a sandwich cost?",
    ]

    for task in tasks:
        print(f"\n{'─' * 60}")
        print(f"Task: {task}")
        print(f"{'─' * 60}")

        result = await agent.run(task)

        print(f"Answer: {result.final_output}")
        print(f"Steps: {result.total_steps} | Tool calls: {result.total_tool_calls} | "
              f"Tokens: {result.total_usage.total}")


if __name__ == "__main__":
    asyncio.run(main())
