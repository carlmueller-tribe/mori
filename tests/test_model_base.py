"""Tests for ModelAdapter protocol and StreamChunk."""

from mori.model.base import ModelAdapter, StreamChunk
from mori.types import (
    Message,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)


def test_stream_chunk_text_delta():
    chunk = StreamChunk(type="text_delta", text="hello")
    assert chunk.type == "text_delta"
    assert chunk.text == "hello"
    assert chunk.tool_call is None
    assert chunk.usage is None


def test_stream_chunk_usage():
    chunk = StreamChunk(
        type="usage",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )
    assert chunk.usage is not None
    assert chunk.usage.total == 15


def test_model_adapter_is_protocol():
    """ModelAdapter should be a runtime-checkable Protocol."""
    import typing

    is_protocol = getattr(typing, "is_protocol", None)
    # Python 3.12+ uses typing.is_protocol; 3.11 uses _is_runtime_protocol
    assert (
        hasattr(ModelAdapter, "__protocol_attrs__")
        or getattr(ModelAdapter, "_is_runtime_protocol", False)
        or (is_protocol is not None and is_protocol(ModelAdapter))
    )


class FakeAdapter:
    """A minimal implementation to verify the protocol shape."""

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            message=Message(role="assistant", content="fake"),
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )

    async def stream(self, request):
        yield StreamChunk(type="text_delta", text="fake")

    async def count_tokens(self, text: str) -> int:
        return len(text.split())

    @property
    def max_context_tokens(self) -> int:
        return 100000

    @property
    def model_id(self) -> str:
        return "fake-model"

    @property
    def supports_tool_use(self) -> bool:
        return True


def test_fake_adapter_satisfies_protocol():
    adapter = FakeAdapter()
    assert isinstance(adapter, ModelAdapter)


async def test_fake_adapter_invoke():
    adapter = FakeAdapter()
    request = ModelRequest(messages=[Message(role="user", content="hi")])
    response = await adapter.invoke(request)
    assert response.message.content == "fake"
    assert response.stop_reason == "end_turn"
