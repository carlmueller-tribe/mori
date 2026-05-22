"""Tests for HookBlock, HookRetry, YieldToUser exception types."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import HookBlock, HookRetry, YieldToUser


class TestHookBlock:
    def test_carries_reason(self) -> None:
        e = HookBlock("not allowed")
        assert e.reason == "not allowed"
        assert str(e) == "not allowed"

    def test_hook_id_optional(self) -> None:
        e = HookBlock("nope")
        assert e.hook_id is None

    def test_hook_id_settable(self) -> None:
        e = HookBlock("nope", hook_id="hook_abc")
        assert e.hook_id == "hook_abc"

    def test_is_exception(self) -> None:
        with pytest.raises(HookBlock):
            raise HookBlock("test")


class TestHookRetry:
    def test_carries_feedback(self) -> None:
        e = HookRetry("re-think")
        assert e.feedback == "re-think"
        assert str(e) == "re-think"

    def test_hook_id_optional(self) -> None:
        e = HookRetry("re-think")
        assert e.hook_id is None

    def test_is_exception(self) -> None:
        with pytest.raises(HookRetry):
            raise HookRetry("test")


class TestYieldToUser:
    def test_carries_question(self) -> None:
        e = YieldToUser("which db?")
        assert e.question == "which db?"
        assert str(e) == "which db?"

    def test_is_exception(self) -> None:
        with pytest.raises(YieldToUser):
            raise YieldToUser("test")
