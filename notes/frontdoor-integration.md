# Integrating with the Trainer Agent (front door)

> **Interface version: 1.0** — this document IS the spec for that version. The
> running service advertises the same version on every response
> (`X-Trainer-Agent-Interface-Version`), and this doc and the service are bumped
> together. See [Versioning](#versioning) and [Changelog](#changelog).

**Audience:** the app that talks to the Trainer Agent — `jessitron/mtg-deck-shuffler`.
This is everything you need to call the agent and show its replies. You only need
HTTPS + a bearer token to *call* it; you need AWS access once, to *fetch* the token
(below).

## What this is

The Trainer Agent is a coding agent. You chat with it on behalf of a human; it
gathers a coding task, implements it on a branch of this repo, and opens a PR.
You call it **once per user message** (synchronous request/response) and show the
`reply` in your chat UI. State (conversation + working tree) lives server-side,
keyed by the `session_id` you send — so you don't resend history.

## Endpoint

```
POST https://3zpl56dwi54putsdjtecwnyqim0sdjmh.lambda-url.us-west-2.on.aws/
```

Public HTTPS endpoint (a Lambda Function URL). Auth is a **shared bearer token** —
nothing else gates it, so keep the token secret.

## Authentication

Send the shared secret as a bearer token:

```
Authorization: Bearer <TRAINER_AGENT_TOKEN>
```

- A missing/wrong token gets `401 {"error":"unauthorized"}`.

### Fetching the token

The token lives in AWS Secrets Manager. If you have AWS access to the
`jessitron-sandbox` account (profile `sandbox`, us-west-2), fetch it yourself:

```bash
aws secretsmanager get-secret-value \
  --profile sandbox --region us-west-2 \
  --secret-id trainer-agent/frontdoor-bearer \
  --query SecretString --output text
```

Put the result in the app's config as a **secret / env var** (e.g.
`TRAINER_AGENT_TOKEN`) — **do not commit it**. Re-run the command if the secret is
rotated.

## Request

`Content-Type: application/json`. Body:

```json
{
  "message": "the user's chat message",
  "session_id": "a-stable-id-at-least-33-characters-long"
}
```

- **`message`** — the user's text for this turn.
- **`session_id`** — **required, ≥ 33 characters.** Generate one per chat session
  (e.g. `"mtg-deck-shuffler-" + uuid4()`) and **reuse it for every message in that
  conversation.** It keeps the agent's microVM warm and its cloned working tree
  intact across turns. A new id = a fresh conversation. Too short / missing →
  `400 {"error":"session_id required (>= 33 chars)"}`.

## Response

`200` with the agent's JSON:

```json
{
  "reply": "text to show the user in chat",
  "status": "chatting | coding | asking | done | error",
  "pr_url": "https://github.com/jessitron/mtg-deck-shuffler/pull/123"
}
```

- **`reply`** — show this in the chat UI.
- **`status`** — `chatting`/`asking` (it's talking or wants info — keep the
  conversation going), `coding` (working), `done` (finished this task),
  `error` (something failed; `reply` explains).
- **`pr_url`** — present only once a PR exists. Link it in the UI.

### Errors

| HTTP | Body | Meaning |
|------|------|---------|
| 400 | `{"error":"invalid JSON body"}` | body wasn't valid JSON |
| 400 | `{"error":"session_id required (>= 33 chars)"}` | missing/short `session_id` |
| 401 | `{"error":"unauthorized"}` | missing/wrong bearer token |
| 502 | `{"error":"agent invoke failed","detail":"..."}` | the agent runtime failed |

## Timeouts — set a long read timeout

This is **synchronous**: the HTTP call stays open until the agent finishes the
turn. Chat turns return in seconds, but a **coding turn can take minutes**. Set
your HTTP client's read timeout to **at least 300 seconds** (the agent's current
cap). If a call times out, retry with the **same `session_id`** — the conversation
and working tree are intact, so you resume rather than restart.

## Trace propagation (recommended)

The agent is fully traced in Honeycomb. If your app uses OpenTelemetry, **inject
W3C trace context** so your app, the front door, and the agent appear as **one
trace**. Just inject your current context into the outgoing request headers —
standard `traceparent` over HTTP is all the front door needs:

- The front door reads `traceparent` from the request headers.
- It forwards context onward; the agent's spans join your trace automatically.

No extra fields in the body are required from you — the `traceparent` **header**
is enough.

## Versioning

This interface is versioned `MAJOR.MINOR` (currently **1.0**). MAJOR bumps on a
breaking change; MINOR on a backward-compatible addition. The doc and the running
service are bumped together — this doc is the spec for the version it names at the
top.

- **The service advertises its version** on every response:
  `X-Trainer-Agent-Interface-Version: 1.0`.
- **You should declare yours** by sending the same header on each **request**, set
  to the version you built against (e.g. `X-Trainer-Agent-Interface-Version: 1.0`).
- **A mismatch is a warning, not an error.** The front door never rejects a
  request over version; it records *both* versions on its trace span
  (`frontdoor.interface_version` = the service's, `frontdoor.client_interface_version`
  = yours). Drift is caught in Honeycomb, not at runtime. Sending the header is how
  you make that signal useful — if you omit it, the client version logs as `unset`.

## Examples

### curl

```bash
curl -sS -XPOST "https://3zpl56dwi54putsdjtecwnyqim0sdjmh.lambda-url.us-west-2.on.aws/" \
  -H "Authorization: Bearer $TRAINER_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'X-Trainer-Agent-Interface-Version: 1.0' \
  -d '{"message":"Add a shuffle-animation toggle to the deck view","session_id":"mtg-deck-shuffler-3f9c1e6a-2b7d-4a55-9e21-abc123def456"}'
```

### Python (with OTel propagation)

```python
import os, urllib.request, json
from opentelemetry.propagate import inject  # if you use OTel

URL = "https://3zpl56dwi54putsdjtecwnyqim0sdjmh.lambda-url.us-west-2.on.aws/"

def ask_trainer(message: str, session_id: str) -> dict:
    headers = {
        "Authorization": f"Bearer {os.environ['TRAINER_AGENT_TOKEN']}",
        "Content-Type": "application/json",
        "X-Trainer-Agent-Interface-Version": "1.0",  # the version you built against
    }
    inject(headers)  # adds W3C `traceparent` so the trace continues into the agent
    body = json.dumps({"message": message, "session_id": session_id}).encode()
    req = urllib.request.Request(URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:   # long timeout!
        return json.loads(resp.read())
```

(A complete working reference client lives in the trainer-agent repo at
`scripts/propagation_test.py`.)

### TypeScript / Node (fetch)

```ts
const URL = "https://3zpl56dwi54putsdjtecwnyqim0sdjmh.lambda-url.us-west-2.on.aws/";

async function askTrainer(message: string, sessionId: string) {
  const res = await fetch(URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${process.env.TRAINER_AGENT_TOKEN}`,
      "Content-Type": "application/json",
      "X-Trainer-Agent-Interface-Version": "1.0", // the version you built against
      // If you use OTel, inject `traceparent` here so the trace continues.
    },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal: AbortSignal.timeout(300_000), // long timeout for coding turns
  });
  if (!res.ok) throw new Error(`trainer agent ${res.status}: ${await res.text()}`);
  return res.json(); // { reply, status, pr_url? }
}
```

## A minimal chat loop

1. On a new conversation, mint a `session_id` (≥33 chars) and keep it.
2. For each user message: `POST` with that `session_id`; render `reply`.
3. While `status` is `chatting`/`asking`/`coding`, keep letting the user reply.
4. When `pr_url` appears, surface the PR link. `status: done` ends the task.

## Changelog

- **1.0** (2026-06-24) — initial interface. `POST` with `{message, session_id}` +
  bearer auth over the Function URL; response `{reply, status, pr_url?}`; optional
  `traceparent` header for trace propagation; `X-Trainer-Agent-Interface-Version`
  on requests (client) and responses (service).
