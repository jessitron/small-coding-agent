"""Local test stub for the Trainer Agent front door.

A small HTTP server that enforces the SAME request contract as the real front
door (``frontdoor/contract.py`` — shared, so it can't drift) but returns CANNED
replies instead of invoking the real agent. mtg-deck-shuffler runs this as a test
sidecar (``docker run``) to exercise its integration end to end — bearer auth,
request validation, the version header, and its own handling of
``reply``/``status``/``pr_url`` — entirely locally, with no AWS and no real agent.

The canned ``status`` is driven by the message text so the app can test each
branch of its UI:

  - "open the pr" / "pr please"  -> status "done"  + a fake ``pr_url``
  - "ask"                        -> status "asking"
  - "error" / "fail"             -> status "error"
  - otherwise                    -> status "chatting"

Observability: the stub is instrumented with OpenTelemetry. Each request emits a
``frontdoor-stub.invocation`` span carrying ``stub.faking=true`` (so it is
unmistakable in Honeycomb that this is the fake, not the real agent). It joins the
caller's trace via W3C context on the incoming request headers, mirroring the real
front door. Spans export via OTLP/HTTP using the standard ``OTEL_*`` env vars; if
no endpoint is configured the tracer is a no-op, so the stub still runs (and
``scripts/stub-smoke.sh`` still passes) without a collector.

Run:   ``python3 stub.py``   (or via the published Docker image)
Env:   ``PORT`` (default 8080); ``STUB_BEARER`` — the token the app must present
       (default ``stub-token``); ``OTEL_*`` — tracing export config;
       ``OTEL_SERVICE_NAME`` (default ``trainer-agent-frontdoor-stub``).
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from contract import (
    INTERFACE_VERSION,
    INTERFACE_VERSION_HEADER,
    validate_request,
)

BEARER = os.environ.get("STUB_BEARER", "stub-token")
PORT = int(os.environ.get("PORT", "8080"))


def _endpoint_configured() -> bool:
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def configure_tracing() -> None:
    """Install the global tracer provider. No-op if no OTLP endpoint is set, so
    the stub still runs (and smoke tests still pass) without a collector."""
    if not _endpoint_configured():
        return
    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "trainer-agent-frontdoor-stub")}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


_tracer = trace.get_tracer("frontdoor.stub")


def canned_reply(message):
    m = (message or "").lower()
    if "open the pr" in m or "pr please" in m:
        return {
            "reply": "[stub] opened a PR",
            "status": "done",
            "pr_url": "https://github.com/jessitron/mtg-deck-shuffler/pull/0",
        }
    if "ask" in m:
        return {"reply": "[stub] I have a question for you", "status": "asking"}
    if "error" in m or "fail" in m:
        return {"reply": "[stub] something went wrong", "status": "error"}
    return {"reply": "[stub] hi", "status": "chatting"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header(INTERFACE_VERSION_HEADER, INTERFACE_VERSION)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""

        # Join the caller's trace (W3C context on the request headers), mirroring
        # the real front door.
        carrier = {k.lower(): v for k, v in self.headers.items()}
        parent_ctx = extract(carrier)

        with _tracer.start_as_current_span(
            "frontdoor-stub.invocation", context=parent_ctx
        ) as span:
            # Make it unmistakable this is the fake, not the real agent.
            span.set_attribute("stub.faking", True)
            span.add_event(
                "faking the trainer agent — returning a canned reply "
                "(no real agent, no AWS, no PR)"
            )

            result = validate_request(self.headers, raw, BEARER)
            if result[0] == "error":
                _, status, body = result
                span.set_attribute("agent.status", "error")
                span.set_status(
                    trace.Status(trace.StatusCode.ERROR, body.get("error", "invalid request"))
                )
                return self._send(status, body)

            _, req = result
            message = req.get("message", "")
            span.set_attribute("agent.message", message)

            reply = canned_reply(message)
            span.set_attribute("agent.status", reply["status"])
            span.set_attribute("agent.reply", reply["reply"])
            if reply.get("pr_url"):
                span.set_attribute("pr.url", reply["pr_url"])
            if reply["status"] == "error":
                span.set_status(trace.Status(trace.StatusCode.ERROR, reply["reply"]))

            self._send(200, reply)

    def do_GET(self):
        if self.path == "/ping":
            return self._send(200, {"status": "ok", "stub": True})
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # keep test output quiet
        pass


if __name__ == "__main__":
    configure_tracing()
    print(f"front-door stub listening on :{PORT} (interface {INTERFACE_VERSION})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
