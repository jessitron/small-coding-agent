# SEAMAP — small-coding-agent

## North Star
Make apps self-improving from within — from inside an app, a person chats with a
coding agent about how they want the app to change, and the agent opens PRs
against that very app. Generalizing this across many apps is for another day; for
now `jessitron/mtg-deck-shuffler` is the one app gaining the superpower, and this
repo is the agent that grants it. The North Star is the *concept*.

## The Mountains
Sail toward one at a time:

1. **Deployed & wired up** — a dead-simple agent (just says "hi") running on
   Bedrock AgentCore Runtime, invokable over the authed web endpoint, talking to
   my app. Proves the whole pipe end-to-end before there's any coding logic.
2. **First PR from a script** — the agent loop grows up: clones
   `mtg-deck-shuffler`, makes a change, opens a real PR. The chat-to-PR loop
   closes.
3. **Observable in Honeycomb** — traces showing the event loop, raw model I/O on
   spans, tool calls, and the clone / open_pr spans. We can *see* what the agent
   did.

## Safe Harbor
*(a state, not a task — and the bar rises over time)*

Right now: **we can see the agent working in Honeycomb** — a real run produces
traces that show the loop doing its job. Deployment on AgentCore is where the bar
rises to next, but full deployment isn't the bar today.

## Success looks like
- The agent is **honest** — when it's confused or the session times out, it says
  so in chat *and* in telemetry rather than failing silently.
- The chat feels **responsive** — fast enough that holding a conversation with it
  isn't a chore.
- PRs land **within ~15 minutes**, usually.
- The PRs **eventually get accepted** — good enough to merge, not just good
  enough to open.

## How will we know it's working?
- **Honesty:** timeouts and confusion show up as a distinct `status`
  (`asking` / `error`) in chat *and* as a marked span/attribute in Honeycomb — we
  can query for them; they're never silent.
- **Responsive:** per-invoke chat round-trip latency is visible in Honeycomb and
  comfortable for the chatting turns.
- **15-min PRs:** trace duration from first message to `pr_url` (stamped on the
  span) — we can query the distribution and see most under 15 minutes.
- **Accepted:** PRs opened against `mtg-deck-shuffler` actually get merged
  (tracked by hand — merge rate over time).

## Enabling Constraints
- **Strands Agents (Python), not the Claude Agent SDK** — chosen for
  observability and for dogfooding the standard customer stack.
- **One agent loop**, no separate chat/code modes — it can ask clarifying
  questions mid-coding and resume with the working tree intact.
- **One target repo** (`jessitron/mtg-deck-shuffler`), one PR per session —
  single-purpose by design.
- **Observability is first-class**: standard OTel to Honeycomb, raw LLM I/O on
  spans. Non-negotiable, not bolted on later.
- **Secrets stay out of the image** — GitHub PAT in a secret store / gitignored
  `.env`.
- **Deploy via Dockerfile** (over the starter-toolkit CodeBuild path).

## Non-goals
- **Generalizing across many apps** — the reusable "drop this agent into any app"
  capability is the North Star concept but explicitly another day's work.
- **AgentCore Memory** — deferred until after v1; conversation state lives in the
  session workspace dir for now.
- **Streaming responses** — request/response is fine.
- **Owning the chat UI / websocket** — that belongs to the *other* app; this repo
  is just the invokable agent.
- **Multiple repos or multiple PRs per session** — one repo, one task, one PR.

## Tracking

Where the live work for this project is recorded. (Adapter contract:
`seamapping/TRACKING-ADAPTER.md`.)

- backend: in-repo

Open work lives in `TODO.md`; durable learnings and a done-log live in `notes/`.
