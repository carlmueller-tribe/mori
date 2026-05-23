"""Tests for fizzbuzz.py."""

from __future__ import annotations

import pytest

from fizzbuzz import fizzbuzz


@pytest.mark.parametrize(
    "n,expected",
    [
        (1, "1"),
        (2, "2"),
        (3, "Fizz"),
        (4, "4"),
        (5, "Buzz"),
        (6, "Fizz"),
        (9, "Fizz"),
        (10, "Buzz"),
        (15, "FizzBuzz"),
        (30, "FizzBuzz"),
    ],
)
def test_fizzbuzz(n: int, expected: str) -> None:
    assert fizzbuzz(n) == expected
