"""Trace-propagation test client — stands in for the calling app.

Starts a real root span (service.name=trainer-agent-test-client), exports it to
the SAME Boswell collector the front door and agent use, and calls the front-door
Function URL with the W3C ``traceparent`` header injected. If propagation works,
Honeycomb shows ONE trace spanning three services:

    trainer-agent-test-client  ->  trainer-agent-frontdoor  ->  trainer-agent

Run via scripts/propagation-test.sh, which wires the OTEL_* env (Boswell) and
passes FRONTDOOR_URL / FRONTDOOR_BEARER / SESSION_ID. Prints the trace id so you
can find the trace in Honeycomb (team modernity, env cynditaylor-com-bot).
"""

import json
import os
import sys
import urllib.request

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

FRONTDOOR_URL = os.environ["FRONTDOOR_URL"]
FRONTDOOR_BEARER = os.environ["FRONTDOOR_BEARER"]
SESSION_ID = os.environ.get("SESSION_ID", "trainer-agent-propagation-test-session-0001")

resource = Resource.create({"service.name": "trainer-agent-test-client"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("propagation-test")


def main() -> int:
    with tracer.start_as_current_span("test.client.request") as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        print(f"== trace_id: {trace_id}")

        # Inject the current trace context into the outgoing HTTP headers.
        headers = {
            "Authorization": f"Bearer {FRONTDOOR_BEARER}",
            "Content-Type": "application/json",
        }
        inject(headers)  # adds 'traceparent' (and tracestate/baggage if present)
        print(f"== traceparent: {headers.get('traceparent')}")

        body = json.dumps(
            {"message": "hello from the propagation test", "session_id": SESSION_ID}
        ).encode("utf-8")
        req = urllib.request.Request(FRONTDOOR_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as e:
            print(f"FAIL: HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
            return 1

        print(f"== response ({status}): {payload}")
        span.set_attribute("test.frontdoor.status_code", status)
        ok = status == 200 and '"reply": "hi"' in payload

    provider.force_flush(5000)
    provider.shutdown()

    if ok:
        print("PASS — now confirm ONE trace spans test-client -> frontdoor -> agent")
        print(f"       Honeycomb (team modernity, env cynditaylor-com-bot), trace_id={trace_id}")
        return 0
    print("FAIL: unexpected response")
    return 1


if __name__ == "__main__":
    sys.exit(main())
