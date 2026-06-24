# Integrating with the Trainer Agent (front door)

**Audience:** the app that talks to the Trainer Agent — `jessitron/mtg-deck-shuffler`.
This is everything you need to call the agent and show its replies. You do **not**
need AWS credentials or the AWS SDK — just HTTPS and a bearer token.

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

- Jessitron will give you the token value. Store it as a **secret / env var** in
  the app's deployment (e.g. `TRAINER_AGENT_TOKEN`). **Do not commit it.**
- A missing/wrong token gets `401 {"error":"unauthorized"}`.
- (For reference, the source of truth is AWS Secrets Manager
  `trainer-agent/frontdoor-bearer` in account 414852377253, us-west-2. The app
  shouldn't read that directly — it just needs the value in its own config.)

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

## Examples

### curl

```bash
curl -sS -XPOST "https://3zpl56dwi54putsdjtecwnyqim0sdjmh.lambda-url.us-west-2.on.aws/" \
  -H "Authorization: Bearer $TRAINER_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
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
