"""Trainer Agent entrypoint for Amazon Bedrock AgentCore Runtime.

The Trainer Agent trains ``jessitron/mtg-deck-shuffler`` to give better in-game
recommendations: it chats with a human (through another app, over synchronous
HTTP), implements a coding task on a branch, and opens a PR.

This module is the minimal scaffold. It stands up the AgentCore harness and
replies "hi", proving the deploy pipe end to end. The Strands agent loop, GitHub
tools, and observability arrive in later landings (see TODO.md).

Run locally::

    uv run agent

then in another shell::

    curl -XPOST http://localhost:8080/invocations \
        -H 'Content-Type: application/json' \
        -d '{"message": "hello"}'

AgentCore serves the entrypoint at ``POST /invocations`` on port 8080, with a
health check at ``GET /ping``.
"""

from bedrock_agentcore import BedrockAgentCoreApp
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.propagate import extract

from agent.observability import configure_tracing, flush

# Load local .env (OTEL_* etc.) before configuring tracing. In prod there is no
# .env in the image; the AgentCore runtime supplies the env vars and this no-ops.
load_dotenv()
configure_tracing()

app = BedrockAgentCoreApp()
_tracer = trace.get_tracer("agent.main")


@app.entrypoint
def invoke(payload, context=None):
    """Handle one chat turn.

    Request/response follow the invoke contract in ``design/architecture.md``:

        request:  {"message": "user's chat message"}
        response: {"reply": "...", "status": "chatting|coding|asking|done|error",
                   "pr_url": "https://github.com/.../pull/123"}

    ``runtimeSessionId`` is carried by AgentCore (on ``context``), not in the body.
    Each turn is one ``agent.invocation`` span; spans are flushed before returning
    so they leave the microVM before AgentCore may freeze it.

    The trace does **not** start here: the caller (the front-door Lambda, and
    behind it the app) propagates W3C trace context via the ``InvokeAgentRuntime``
    ``traceParent``/``traceState``/``baggage`` params. AgentCore forwards those as
    request headers (see ``context.request_headers``), and we extract them so
    ``agent.invocation`` joins the caller's trace instead of rooting its own. If
    no context is forwarded (e.g. a bare ``cloud-smoke`` invoke), we root a span.
    """
    message = payload.get("message", "")
    session_id = getattr(context, "session_id", None)

    # Extract propagated trace context from the forwarded request headers. Keys
    # may arrive in any case (HTTP/2 lowercases; HTTP/1.1 may not), so normalize.
    headers = getattr(context, "request_headers", None) or {}
    carrier = {k.lower(): v for k, v in headers.items()}
    parent_ctx = extract(carrier)

    with _tracer.start_as_current_span("agent.invocation", context=parent_ctx) as span:
        if session_id:
            span.set_attribute("session.id", session_id)
        span.set_attribute("agent.message", message)
        reply = {"reply": "hi", "status": "chatting"}
        span.set_attribute("agent.reply", reply["reply"])
        span.set_attribute("agent.status", reply["status"])

    flush()
    return reply


def main():
    """Console-script entrypoint: start the AgentCore HTTP server."""
    app.run()


if __name__ == "__main__":
    main()
