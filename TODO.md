# TODO — small-coding-agent

Open work, in buckets. (This is the in-repo tracking store; see `SEAMAP.md` §Tracking.)
Checkbox marks status: `[ ]` backlog/next, `[~]` started, `[x]` done, `[!]` standing.
A trailing `←` comment carries `mountain:`, `priority:`, `tag:`, `standing`.

## In progress

## Next

- [ ] Verify warm-VM batching delivers end-of-session spans without per-invoke flush; if so, drop the flush to protect chat latency ← Safe Harbor; priority: medium
- [ ] Wire my app to invoke the agent — POST to the front-door Function URL with the bearer + a stable `session_id` (and a `traceparent`), show the reply ← mountain: Deployed & wired up; priority: medium
  - The front door is live (see done.md 2026-06-24): `POST <function-url>` with `Authorization: Bearer <secret>` and `{"message","session_id"}`. The app should start a span and inject `traceparent` so its trace continues through frontdoor → agent. `scripts/propagation_test.py` is a working reference client.

## Backlog

- [ ] Consider adding local testing to the Safe Harbor definition in `SEAMAP.md` ← priority: low
  - Surfaced 2026-06-24 while building the Dockerfile + smoke harness. The harbor (a resting _state_) is currently just "we can see the agent working in Honeycomb". Question: should the bar also reflect that we can test the agent locally across the layers (`notes/local-testing-advice.md`) _before_ trusting a deploy — i.e. "works locally" genuinely predicts "works in cloud"? Decide whether that's a Safe-Harbor property or just a working habit; edit the `## Safe Harbor` section if so.
- [ ] Async callback alternative to the blocking front-door Lambda ← mountain: Deployed & wired up; priority: low; related: "Add an authed web endpoint", "Wire my app to invoke the agent"
  - Surfaced 2026-06-24 as a deferred-architecture follow-up while choosing the front-door design. Instead of the app holding a synchronous HTTP connection open while the agent codes (the current chosen design — a blocking Lambda behind a Function URL), the agent could make an **async callback** to the calling app when it finishes. Jessitron noted this "probably makes it more of a websocket on the mtg-deck-shuffler side."
  - **Postponed deliberately**: the blocking Lambda costs under 1¢ per coding invoke (arm64, 128MB), so the simple synchronous design wins for now.
  - **Revisit if** invoke latency, the Lambda 15-min timeout cap, or cost ever start to matter — or when wiring the real app (the two related items under Mountain 1) reveals the synchronous hold is awkward in practice.

- [ ] Copy the boswell collector code, rename it to our own, and deploy our own collector-as-lambda. Then we are free to send to our own environment and control our own processors. Add one for calculating the lambda cost from the hard-coded rate attributes.

- [ ] Open question. The lambda puts the trace context in the payload to make sure it goes through. Something about arbitrary headers might not? Investigate whether there is a standard propagation mechanism that would work. This is for Jess's otel knowledge.

## Owners
