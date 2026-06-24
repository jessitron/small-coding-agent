"""Front-door Lambda for the Trainer Agent.

A thin authenticated proxy that sits in front of the AgentCore runtime so the
calling app can use a plain ``Authorization: Bearer <secret>`` over a public
HTTPS Function URL instead of signing AWS SigV4 requests itself. Per request it:

1. validates the bearer token (shared secret, from Secrets Manager);
2. continues the caller's trace (W3C context from the request headers) and opens
   a ``frontdoor.invoke`` span stamped with the Lambda cost *rate* (cost itself
   is a calculated field downstream — see ``notes/decisions.md``);
3. calls ``InvokeAgentRuntime``, propagating trace context via the native
   ``traceParent``/``traceState``/``baggage`` params (AgentCore forwards those to
   the agent as request headers);
4. returns the agent's ``{reply, status, pr_url?}`` JSON unchanged.

Telemetry-from-Lambda gotchas this handles (see notes/telemetry.md):

- **Freeze eats spans.** Lambda freezes the environment the instant the handler
  returns, suspending any background export thread. We use ``SimpleSpanProcessor``
  (synchronous export on the handler thread) so there is no thread to freeze —
  freeze-proof by construction, unlike the agent's BatchSpanProcessor (which
  needs an explicit force-flush because it emits many spans per turn; we emit ~1).
- **Cold-start cost.** The TracerProvider and boto3 client are built once at
  module import, reused across warm invocations — never per request.
- **Telemetry must never break the request.** Provider setup and the agent call
  are independent; a dead collector can't fail a chat turn.
"""

import hmac
import json
import os

import boto3
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind

# --- module scope: built once per cold start, reused while warm ---------------

REGION = os.environ["AWS_REGION"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
BEARER_SECRET_ID = os.environ["BEARER_SECRET_ID"]

# Version of the app-facing interface (request/response contract + headers).
# MUST stay in sync with notes/frontdoor-integration.md, which is the spec the
# mtg-deck-shuffler app integrates against. Bump the MAJOR on a breaking change,
# the MINOR on a backward-compatible addition. Advertised on every response via
# the X-Trainer-Agent-Interface-Version header and stamped on the span.
INTERFACE_VERSION = "1.0"

# Lambda price *rate* (arm64, us-west-2 list price). Hard-coded here; the dollar
# cost per invoke is derived in Honeycomb as rate x duration, so we can re-price
# without redeploying. See notes/decisions.md.
RATE_GB_SECOND = 0.0000133334
RATE_PER_REQUEST = 0.0000002

_boto = boto3.client("bedrock-agentcore", region_name=REGION)
_secrets = boto3.client("secretsmanager", region_name=REGION)


def _configure_tracing():
    """Install the tracer provider once. OTLP endpoint/headers come from OTEL_*
    env vars (Boswell, set by deploy-frontdoor.sh), same as the agent. No
    endpoint -> default no-op tracer, so the proxy still works without a
    collector."""
    if not (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    ):
        return
    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "trainer-agent-frontdoor")}
    )
    provider = TracerProvider(resource=resource)
    # SimpleSpanProcessor: synchronous export, no background thread for the
    # Lambda freeze to suspend. See module docstring.
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


_configure_tracing()
_tracer = trace.get_tracer("frontdoor")

# Cache the bearer secret across warm invokes (one Secrets Manager call per cold
# start). Fetched lazily so a missing secret surfaces as a 500, not an import
# crash that hides the cause.
_expected_bearer = None


def _bearer_secret():
    global _expected_bearer
    if _expected_bearer is None:
        resp = _secrets.get_secret_value(SecretId=BEARER_SECRET_ID)
        _expected_bearer = resp["SecretString"]
    return _expected_bearer


def _header(headers, name):
    """Case-insensitive header lookup (Function URL lowercases, but be safe)."""
    name = name.lower()
    for k, v in headers.items():
        if k.lower() == name:
            return v
    return None


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "X-Trainer-Agent-Interface-Version": INTERFACE_VERSION,
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    headers = event.get("headers") or {}

    # 1. Authenticate. Constant-time compare to avoid leaking the secret via timing.
    auth = _header(headers, "authorization") or ""
    presented = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not presented or not hmac.compare_digest(presented, _bearer_secret()):
        return _resp(401, {"error": "unauthorized"})

    # 2. Parse the request body: {"message": "...", "session_id": ">=33 chars"}.
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "invalid JSON body"})
    message = body.get("message", "")
    session_id = body.get("session_id")
    # AgentCore requires runtimeSessionId >= 33 chars.
    if not session_id or len(session_id) < 33:
        return _resp(400, {"error": "session_id required (>= 33 chars)"})

    # 3. Continue the caller's trace and proxy the call.
    parent_ctx = extract({k.lower(): v for k, v in headers.items()})
    with _tracer.start_as_current_span(
        "frontdoor.invoke", context=parent_ctx, kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("session.id", session_id)
        # Record both the version we implement and the one the client declares
        # (via the same header on the request). A mismatch is a WARNING, surfaced
        # in telemetry — never an error; we don't reject on it. Compare the two in
        # Honeycomb to spot drift.
        span.set_attribute("frontdoor.interface_version", INTERFACE_VERSION)
        span.set_attribute(
            "frontdoor.client_interface_version",
            _header(headers, "x-trainer-agent-interface-version") or "unset",
        )
        # Lambda cost rate (dollars derived downstream as rate x duration).
        span.set_attribute("lambda.cost.rate_gb_second", RATE_GB_SECOND)
        span.set_attribute("lambda.cost.rate_per_request", RATE_PER_REQUEST)
        mem_mb = getattr(context, "memory_limit_in_mb", None)
        if mem_mb:
            span.set_attribute("lambda.memory_gb", int(mem_mb) / 1024)

        # Inject *this* span's context so the agent parents onto the frontdoor
        # span. AgentCore does NOT forward the native traceParent/traceState
        # params to the container as headers (only `baggage` is forwarded), so
        # the reliable channel to the agent is the PAYLOAD: we carry the W3C
        # context in the body and the agent extracts it. We still pass the native
        # params too, for AgentCore's own internal trace linkage.
        carrier = {}
        inject(carrier)
        agent_payload = {"message": message}
        if carrier.get("traceparent"):
            agent_payload["traceparent"] = carrier["traceparent"]
        if carrier.get("tracestate"):
            agent_payload["tracestate"] = carrier["tracestate"]
        trace_kwargs = {}
        if carrier.get("traceparent"):
            trace_kwargs["traceParent"] = carrier["traceparent"]
        if carrier.get("tracestate"):
            trace_kwargs["traceState"] = carrier["tracestate"]
        if carrier.get("baggage"):
            trace_kwargs["baggage"] = carrier["baggage"]

        try:
            result = _boto.invoke_agent_runtime(
                agentRuntimeArn=AGENT_RUNTIME_ARN,
                runtimeSessionId=session_id,
                contentType="application/json",
                accept="application/json",
                payload=json.dumps(agent_payload).encode("utf-8"),
                **trace_kwargs,
            )
        except Exception as exc:  # surface upstream failures as 502, on the span
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            return _resp(502, {"error": "agent invoke failed", "detail": str(exc)})

        raw = result["response"].read()
        agent_reply = json.loads(raw)
        span.set_attribute("agent.status", agent_reply.get("status", ""))
        if agent_reply.get("pr_url"):
            span.set_attribute("pr.url", agent_reply["pr_url"])

    return _resp(200, agent_reply)
