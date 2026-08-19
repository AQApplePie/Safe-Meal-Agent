"""OpenTelemetry bootstrap and JSONL-to-OTel bridge."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)

from safemeal.config.settings import Settings
from safemeal.shared.types import JsonObject


def configure_telemetry(application: Any, settings: Settings) -> None:
    """Configure OTLP when enabled; leave application semantics unchanged."""

    if not settings.ENABLE_OTEL:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.OTEL_SERVICE_NAME,
                "service.version": settings.APP_VERSION,
                "deployment.environment.name": settings.APP_ENV,
            }
        )
    )
    exporter: SpanExporter
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=settings.OTEL_EXPORTER_OTLP_INSECURE,
        )
    else:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(application, tracer_provider=provider)


def export_agent_trace(payload: JsonObject) -> None:
    """Mirror the completed JSONL run into OTel/LLMOps-compatible spans."""

    tracer = trace.get_tracer("safemeal.agent")
    with tracer.start_as_current_span("agent.run") as run:
        run.set_attribute("gen_ai.operation.name", "invoke_agent")
        run.set_attribute("gen_ai.conversation.id", str(payload.get("session_id", "")))
        run.set_attribute("safemeal.run_id", str(payload.get("run_id", "")))
        run.set_attribute("safemeal.status", str(payload.get("status", "")))
        run.set_attribute("safemeal.iterations", int(payload.get("iterations", 0) or 0))
        for item in (
            payload.get("spans", []) if isinstance(payload.get("spans"), list) else []
        ):
            if not isinstance(item, dict):
                continue
            with tracer.start_as_current_span(
                str(item.get("name") or "agent.stage")
            ) as child:
                child.set_attribute("safemeal.span.kind", str(item.get("kind", "")))
                child.set_attribute("safemeal.span.status", str(item.get("status", "")))


__all__ = ["configure_telemetry", "export_agent_trace"]
