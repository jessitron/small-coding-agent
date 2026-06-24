"""OpenTelemetry tracing for the Trainer Agent.

Traces export via OTLP/HTTP to a **Boswell** collector (the shared OTel collector
from the cyndibot repo — see `notes/telemetry.md`):

- **local**: the Boswell collector container on `http://localhost:4318`
  (start it with `scripts/start-collector.sh`).
- **prod**:  the Boswell collector Lambda, shared with cyndibot.

The OTLP exporter reads its endpoint, protocol, and headers from the standard
``OTEL_*`` env vars (loaded from `.env` locally; set on the AgentCore runtime in
prod by `scripts/deploy.sh`). This module only builds the provider + resource.

If no OTLP endpoint is configured, tracing is left as the default no-op tracer so
the agent still runs without a collector.

Why a collector at all (vs. straight to Honeycomb): Strands records gen_ai
input/output as span *events*, and a producer-side ``SpanProcessor`` can't lift
them onto the span (``on_end`` gets a read-only ``ReadableSpan``). Boswell does
that with an OTTL transform. Not exercised yet — the agent only says "hi" — but
the pipe is built the way the real loop will need it.
"""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False


def _endpoint_configured() -> bool:
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def configure_tracing() -> None:
    """Install the global tracer provider once. Safe to call more than once.

    ``service.name`` distinguishes our spans from cyndibot's in the shared
    Honeycomb environment (see `notes/telemetry.md`). ``session.id`` is stamped
    per-invoke on the span, not here, so a reused process can't carry a stale id.
    """
    global _configured
    if _configured:
        return
    _configured = True

    if not _endpoint_configured():
        # No collector configured — leave the default no-op tracer in place.
        return

    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "trainer-agent")}
    )
    provider = TracerProvider(resource=resource)
    # Keep BatchSpanProcessor producer-side (Boswell has no cross-invocation
    # buffer). The OTLPSpanExporter reads endpoint/protocol/headers from OTEL_*.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def flush(timeout_millis: int = 5000) -> None:
    """Force-flush spans so they leave the microVM before AgentCore freezes it.

    Bounded and best-effort: telemetry must never break or hang a chat turn.
    """
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is None:
        return
    try:
        force_flush(timeout_millis)
    except Exception:
        pass
