# Telemetry

The Trainer Agent emits OpenTelemetry traces through **Boswell**, the OTel
collector that lives in the neighboring **cyndibot** repo
(`/Users/jessitron/code/jessitron/cynditaylor-com-bot`). We deliberately reuse
Boswell rather than run our own collector.

## Where traces go — team `modernity` (NOT the Honeycomb MCP's "Demo" team)

| Env | Endpoint | Honeycomb (team `modernity`) |
| --- | --- | --- |
| **local** | `http://localhost:4318/v1/traces` (Boswell collector container) | env **`local`** |
| **prod** (AgentCore) | the Boswell **Lambda** Function URL + `/v1/traces` | env **`cynditaylor-com-bot`** |

**Verify traces in team `modernity`**, filtering `WHERE service.name = "trainer-agent"`
(and `WHERE collector.boswell exists` to confirm they went through Boswell).
There is no `modernity` Honeycomb MCP wired into this repo's Claude session, so
verification is a manual look (or wire one up).

### ⚠️ Shared prod environment (accepted tradeoff)

Boswell exports with one Honeycomb key → **prod traces land in cyndibot's
`cynditaylor-com-bot` env**, intermixed with cyndibot's, separable only by
`service.name`. Jessitron accepted this ("ohwell") rather than stand up a
separate collector. If we ever want our own env: deploy our own Boswell (the
`collector/` module in cyndibot is built to be copied) or have Boswell route by
`service.name`.

## How it's wired

- **Producer** (`src/agent/observability.py`): a `TracerProvider` with
  `service.name=trainer-agent` on the Resource and a `BatchSpanProcessor` →
  `OTLPSpanExporter`. The exporter reads endpoint/protocol/headers from the
  standard `OTEL_*` env vars. `session.id` is stamped per-invoke on the
  `agent.invocation` span (not on the Resource — avoids a stale id on a reused
  process).
- **Local env vars**: `.env` (gitignored; copy from `.env.example`). Token is the
  localhost-only `local-dev-token` Boswell validates — not a secret.
- **Prod env vars**: set on the AgentCore runtime by `scripts/deploy.sh`, which
  fetches the real ingest token from the Boswell Lambda config at deploy time
  (`aws lambda get-function-configuration --function-name boswell`) so it's never
  committed.
- **Don't send `x-honeycomb-team`** from the producer — Boswell adds the Honeycomb
  key on egress.
- **Why a collector at all**: Strands records gen_ai input/output as span *events*;
  a producer-side `SpanProcessor` can't lift them onto the span. Boswell's OTTL
  transform does. Not exercised yet (agent only says "hi").

## Trace propagation — app → front door → agent (one trace)

The trace starts in the **caller**, not the agent. Three services, one trace
(`trainer-agent-test-client → trainer-agent-frontdoor → trainer-agent`), proven
by `scripts/propagation-test.sh`.

- **app → front door**: standard W3C — the caller injects `traceparent` into the
  HTTP request to the Function URL; the Lambda `extract()`s it from the headers.
- **front door → agent**: **not** standard headers. AgentCore forwards only the
  `baggage` header to the container, and does **not** forward the
  `InvokeAgentRuntime` `traceParent`/`traceState` params (it consumes them for its
  own internal trace linkage). So the front door puts `traceparent`/`tracestate`
  in the invoke **payload**, and the agent extracts from the payload (with a header
  fallback). See the gotcha in `notes/infrastructure.md`. Open follow-up in TODO.md:
  is there a standard mechanism that works through AgentCore?
- **Front-door processor**: `SimpleSpanProcessor` (synchronous export), because
  Lambda freezes the env on return and would suspend a `BatchSpanProcessor`'s
  background thread. The agent keeps Batch+flush (many spans per turn).

## Running it

- **Start the local collector**: `scripts/start-collector.sh` (delegates to
  cyndibot's `./run` — documented dependency on that repo; override `CYNDIBOT_REPO`).
- **Emit a span locally**: `scripts/smoke-local.sh` with the collector running.
- **Collector logs**: `docker logs -f cynditaylor-collector`.

## Open gotcha — per-invoke flush vs. latency (verify, then decide)

`observability.flush()` force-flushes after every invoke so spans leave the
microVM before AgentCore may freeze it. **Cost:** each turn blocks until export
completes — locally that was ~3.3s *during the Honeycomb incident* (collector
retrying egress); against a cold Boswell Lambda it's ~4–5s on the first hit.

cyndibot deliberately does **not** per-invoke flush: within a session the
AgentCore microVM stays warm, so the `BatchSpanProcessor`'s background thread
exports on its schedule without blocking the turn. We should **verify the
warm-VM batching actually delivers our end-of-session spans** (grab a real trace)
and, if so, drop the per-invoke flush to protect the "responsive chat" goal.
Until verified, the flush guarantees delivery at a latency cost.

## Status (2026-06-24, after the ingest incident recovered)

- **Local**: ✅ wired + verified to the collector. After recovery, the invoke
  flush dropped from ~3.3s (retrying during the incident) to **0.2s** with clean
  egress logs — i.e. Honeycomb now accepts the export.
- **Prod**: ✅ deployed (runtime revision 2 carries the OTEL_* env). A cloud-smoke
  invoke produced a span that the **Boswell Lambda received, transformed, and
  exported with no errors** (confirmed in `/aws/lambda/boswell` CloudWatch logs).
- **Confirmed in Honeycomb** ✅ (via the `honeycomb-modernity` MCP, once `.mcp.json`
  loaded): the `agent.invocation` span is queryable in **both** envs (`local` and
  `cynditaylor-com-bot`) with `service.name=trainer-agent`, `agent.status=chatting`,
  and `collector.boswell=washere` (proves the Boswell path). **Safe Harbor reached.**
  - To verify from a Claude session, the project `.mcp.json` (`honeycomb-modernity`
    → `https://mcp.honeycomb.io/mcp`) must be loaded — it's a project MCP, so it
    needs session start / approval, not a mid-session add.
