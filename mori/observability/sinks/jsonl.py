"""JsonlSink — write events as JSON Lines to a file."""

from __future__ import annotations

import io

from mori.observability.events import MoriEvent


class JsonlSink:
    def __init__(self, path: str) -> None:
        self._path = path
        self._file: io.TextIOWrapper = open(path, "a", encoding="utf-8")  # noqa: SIM115

    async def write(self, event: MoriEvent) -> None:
        self._file.write(event.model_dump_json() + "\n")

    async def write_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            self._file.write(event.model_dump_json() + "\n")

    async def flush(self) -> None:
        self._file.flush()

    async def close(self) -> None:
        self._file.flush()
        self._file.close()
