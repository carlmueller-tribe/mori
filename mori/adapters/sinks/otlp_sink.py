"""OTLPSink — OpenTelemetry Protocol sink for Mori events."""

from __future__ import annotations

from mori.observability.events import MoriEvent


class OTLPSink:
    """Exports Mori events as OpenTelemetry spans."""

    realtime: bool = False

    def __init__(self, endpoint: str = "http://localhost:4317") -> None:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as e:
            raise ImportError(
                "OTLPSink requires opentelemetry packages. Install with: pip install 'mori[otlp]'"
            ) from e
        exporter = OTLPSpanExporter(endpoint=endpoint)
        self._provider = TracerProvider()
        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer = self._provider.get_tracer("mori")

    async def write(self, event: MoriEvent) -> None:
        with self._tracer.start_as_current_span(event.event_type) as span:
            span.set_attribute("mori.event_id", event.event_id)
            span.set_attribute("mori.run_id", str(event.run_id))
            for k, v in (event.metadata or {}).items():
                if isinstance(v, str | int | float | bool):
                    span.set_attribute(f"mori.{k}", v)

    async def write_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            await self.write(event)

    async def flush(self) -> None:
        ok = self._provider.force_flush()
        if not ok:
            import warnings

            warnings.warn(
                "OTLPSink: force_flush() returned False — some spans may not have been exported.",
                RuntimeWarning,
                stacklevel=2,
            )

    async def close(self) -> None:
        ok = self._provider.force_flush()
        if not ok:
            import warnings

            warnings.warn(
                "OTLPSink: force_flush() returned False during close"
                " — some spans may not have been exported.",
                RuntimeWarning,
                stacklevel=2,
            )
        self._provider.shutdown()
