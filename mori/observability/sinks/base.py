"""Sink protocol — implemented by all observability output targets."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mori.observability.events import MoriEvent


@runtime_checkable
class Sink(Protocol):
    realtime: bool

    async def write(self, event: MoriEvent) -> None: ...
    async def write_batch(self, events: list[MoriEvent]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
