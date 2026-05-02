"""ModelAdapter protocol and stream types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from mori.types import (
    ModelRequest,
    ModelResponse,
    MoriModel,
    TokenUsage,
    ToolCall,
)


class StreamChunk(MoriModel):
    type: Literal["text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "usage"]
    text: str | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    """Abstraction over LLM provider APIs."""

    async def invoke(self, request: ModelRequest) -> ModelResponse: ...

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]: ...

    async def count_tokens(self, text: str) -> int: ...

    @property
    def max_context_tokens(self) -> int: ...

    @property
    def model_id(self) -> str: ...

    @property
    def supports_tool_use(self) -> bool: ...
