"""Anthropic Claude model adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

from mori.model.base import StreamChunk
from mori.types import (
    Message,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
)

# Model context windows
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-3-5-20241022": 200_000,
}
_DEFAULT_CONTEXT = 200_000


class AnthropicAdapter:
    """Wraps the Anthropic SDK for Claude models."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_tokens: int = 4096,
        base_url: str | None = None,
    ) -> None:
        if anthropic is None:
            raise ImportError("Install anthropic: pip install mori[anthropic]")

        self._model = model
        self._max_tokens = max_tokens
        kwargs: dict[str, Any] = {}
        # Detect OAuth bearer tokens (e.g. from `claude setup-token`) by prefix
        # and route them via auth_token. Anthropic Console API keys go via api_key.
        import os

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        is_oauth = bool(key and key.startswith("sk-ant-oat"))
        if key:
            if is_oauth:
                kwargs["auth_token"] = key
            else:
                kwargs["api_key"] = key
        if base_url:
            kwargs["base_url"] = base_url

        if is_oauth:
            # The SDK reads ANTHROPIC_API_KEY from env automatically and sends
            # BOTH headers if both api_key and auth_token are populated
            # (causing a 401). Temporarily clear ANTHROPIC_API_KEY during
            # client construction so the SDK's env auto-detection doesn't
            # populate `api_key`; restore env afterwards so we don't leak
            # the mutation to other code in the process.
            saved = os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                self._client = anthropic.AsyncAnthropic(**kwargs)
            finally:
                if saved is not None:
                    os.environ["ANTHROPIC_API_KEY"] = saved
        else:
            self._client = anthropic.AsyncAnthropic(**kwargs)

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def supports_tool_use(self) -> bool:
        return True

    @property
    def max_context_tokens(self) -> int:
        return _CONTEXT_WINDOWS.get(self._model, _DEFAULT_CONTEXT)

    def _extract_system(self, messages: list[Message]) -> tuple[str | None, list[Message]]:
        """Extract the system message (Anthropic uses a separate parameter)."""
        system: str | None = None
        remaining: list[Message] = []
        for msg in messages:
            if msg.role == "system":
                system = msg.content if isinstance(msg.content, str) else str(msg.content)
            else:
                remaining.append(msg)
        return system, remaining

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Mori messages to Anthropic message format.

        Merges consecutive tool result messages into a single user message
        (Anthropic requires alternating user/assistant roles).
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content if isinstance(msg.content, str) else str(msg.content),
                }
                # Merge consecutive tool results into one user message
                if (
                    converted
                    and converted[-1]["role"] == "user"
                    and isinstance(converted[-1]["content"], list)
                    and converted[-1]["content"]
                    and converted[-1]["content"][0].get("type") == "tool_result"
                ):
                    converted[-1]["content"].append(tool_result_block)
                else:
                    converted.append(
                        {
                            "role": "user",
                            "content": [tool_result_block],
                        }
                    )
            elif msg.role == "assistant" and msg.tool_calls:
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                converted.append({"role": "assistant", "content": content_blocks})
            else:
                converted.append(
                    {
                        "role": msg.role,
                        "content": msg.content if isinstance(msg.content, str) else msg.content,
                    }
                )
        return converted

    def _convert_tools(self, specs: list[ToolSpec]) -> list[dict[str, Any]]:
        """Convert Mori ToolSpecs to Anthropic tool format."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in specs
        ]

    def _parse_response(self, raw_response: Any) -> ModelResponse:
        """Parse an Anthropic response into a Mori ModelResponse."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in raw_response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        content = "".join(text_parts)
        message = Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )

        return ModelResponse(
            message=message,
            usage=TokenUsage(
                input_tokens=raw_response.usage.input_tokens,
                output_tokens=raw_response.usage.output_tokens,
            ),
            stop_reason=raw_response.stop_reason,
            raw=raw_response.model_dump() if hasattr(raw_response, "model_dump") else {},
        )

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        """Send a request and return a parsed response."""
        system, messages = self._extract_system(request.messages)
        converted_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": converted_messages,
            "max_tokens": request.max_tokens or self._max_tokens,
        }

        if system:
            kwargs["system"] = system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences
        if request.tools:
            kwargs["tools"] = self._convert_tools(request.tools)

        raw_response = await self._client.messages.create(**kwargs)
        return self._parse_response(raw_response)

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        """Stream a response. Not implemented in v0.1."""
        raise NotImplementedError("Streaming will be added in v0.2")
        yield  # Make this a generator  # pragma: no cover

    async def count_tokens(self, text: str) -> int:
        """Approximate token count (4 chars per token heuristic for v0.1)."""
        return len(text) // 4
