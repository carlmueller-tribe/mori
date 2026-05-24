"""The Active Hooks public API must be importable from the top-level `mori` package."""

from __future__ import annotations


def test_hook_exceptions_top_level_importable() -> None:
    from mori import HookBlock, HookRetry

    assert HookBlock is not None
    assert HookRetry is not None


def test_hook_events_top_level_importable() -> None:
    from mori import HookEvents, TurnEndReason

    assert HookEvents.TURN_START == "turn.start"
    assert TurnEndReason.COMPLETED == "completed"


def test_turn_payloads_top_level_importable() -> None:
    from mori import TurnStartPayload, TurnEndPayload

    assert TurnStartPayload is not None
    assert TurnEndPayload is not None


def test_yield_to_user_NOT_top_level_importable() -> None:
    """YieldToUser is intentionally internal — must NOT be in mori.__all__."""
    import mori

    assert "YieldToUser" not in getattr(mori, "__all__", [])
    # Direct attribute access also should not work
    assert not hasattr(mori, "YieldToUser")
