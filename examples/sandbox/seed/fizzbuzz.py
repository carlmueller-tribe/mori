"""FizzBuzz with a deliberate bug for the agent to fix.

Spec:
  - Multiples of 3 → "Fizz"
  - Multiples of 5 → "Buzz"
  - Multiples of both → "FizzBuzz"
  - Otherwise → str(n)

The current implementation is wrong on multiples of 3 — it returns "Buzz"
instead of "Fizz". The test suite in test_fizzbuzz.py catches this.
"""

from __future__ import annotations


def fizzbuzz(n: int) -> str:
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Buzz"  # BUG: should be "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)


if __name__ == "__main__":
    for i in range(1, 16):
        print(f"{i}: {fizzbuzz(i)}")
