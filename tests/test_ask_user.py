"""ask_user tool yields via YieldToUser exception."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import YieldToUser
from mori.tools.native.ask_user import ask_user


@pytest.mark.asyncio
async def test_ask_user_raises_yield_to_user() -> None:
    with pytest.raises(YieldToUser) as exc:
        await ask_user("which db?")
    assert exc.value.question == "which db?"


@pytest.mark.asyncio
async def test_ask_user_question_is_required() -> None:
    with pytest.raises(TypeError):
        await ask_user()  # type: ignore[call-arg]
