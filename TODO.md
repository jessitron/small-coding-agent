# TODO — small-coding-agent

Open work, in buckets. (This is the in-repo tracking store; see `SEAMAP.md` §Tracking.)
Checkbox marks status: `[ ]` backlog/next, `[~]` started, `[x]` done, `[!]` standing.
A trailing `←` comment carries `mountain:`, `priority:`, `tag:`, `standing`.

## In progress

## Next

- [x] Eyeball a trace in Honeycomb (team `modernity`, envs `local` + `cynditaylor-com-bot`) ← Safe Harbor; DONE 2026-06-24
  - Confirmed via the `honeycomb-modernity` MCP: `agent.invocation` span in both envs, `service.name=trainer-agent`, `agent.status=chatting`, `collector.boswell=washere` (proves the Boswell path). **Safe Harbor reached.**
- [ ] Verify warm-VM batching delivers end-of-session spans without per-invoke flush; if so, drop the flush to protect chat latency ← Safe Harbor; priority: medium
- [ ] Add an authed web endpoint — open endpoint + bearer-token validation (shared secret with my app) ← mountain: Deployed & wired up; priority: medium
- [ ] Wire my app to invoke the agent (InvokeAgentRuntime with a stable runtimeSessionId) and show the reply ← mountain: Deployed & wired up; priority: medium

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
