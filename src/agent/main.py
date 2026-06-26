"""Trainer Agent entrypoint for Amazon Bedrock AgentCore Runtime.

The Trainer Agent trains ``jessitron/mtg-deck-shuffler`` to give better in-game
recommendations: it chats with a human (through another app, over synchronous
HTTP), implements a coding task on a branch, and opens a PR.

Each invoke is one chat turn: clone the repo (first turn) and load the app's
brief (``agent.workspace``), then run one Strands turn (``agent.loop``) that
reasons over the brief + the user's message + the game state and replies. The
agent loop, tools, and session persistence live in ``agent.loop``; this module
is the AgentCore harness + trace plumbing.

Run locally::

    uv run agent

then in another shell::

    curl -XPOST http://localhost:8080/invocations \
        -H 'Content-Type: application/json' \
        -d '{"message": "hello", "session_id": "...>=33 chars..."}'

AgentCore serves the entrypoint at ``POST /invocations`` on port 8080, with a
health check at ``GET /ping``.
"""

import os

# Opt into GenAI semantic conventions + message-content capture BEFORE strands is
# imported (via agent.loop), so model spans carry raw LLM I/O. Overridable by the
# environment; see design/architecture.md §Observability.
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.propagate import extract  # noqa: E402

from agent.loop import run_turn  # noqa: E402
from agent.observability import configure_tracing, flush  # noqa: E402

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
    behind it the app) propagates W3C trace context so ``agent.invocation`` joins
    the caller's trace instead of rooting its own. AgentCore does **not** forward
    the ``InvokeAgentRuntime`` ``traceParent``/``traceState`` params to the
    container as request headers (only ``baggage`` is forwarded), so the front
    door carries the context in the **payload** (``traceparent``/``tracestate``).
    We prefer the payload and fall back to any forwarded headers. If no context
    is present (e.g. a bare ``cloud-smoke`` invoke), we root a span.
    """
    message = payload.get("message", "")
    session_id = getattr(context, "session_id", None)

    # Build a W3C carrier from the payload (primary channel), falling back to any
    # forwarded request headers. Header keys may arrive in any case, so normalize.
    headers = getattr(context, "request_headers", None) or {}
    carrier = {k.lower(): v for k, v in headers.items()}
    if payload.get("traceparent"):
        carrier["traceparent"] = payload["traceparent"]
    if payload.get("tracestate"):
        carrier["tracestate"] = payload["tracestate"]
    parent_ctx = extract(carrier)

    with _tracer.start_as_current_span("agent.invocation", context=parent_ctx) as span:
        if session_id:
            span.set_attribute("session.id", session_id)
        span.set_attribute("agent.message", message)

        reply = run_turn(payload, session_id)

        span.set_attribute("agent.status", reply["status"])
        span.set_attribute("agent.reply", reply["reply"])
        if reply.get("pr_url"):
            span.set_attribute("pr.url", reply["pr_url"])
        if reply["status"] == "error":
            span.set_status(trace.Status(trace.StatusCode.ERROR, reply["reply"]))

    flush()
    return reply


def main():
    """Console-script entrypoint: start the AgentCore HTTP server."""
    app.run()


if __name__ == "__main__":
    main()
