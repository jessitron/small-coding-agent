# TODO — small-coding-agent

Open work, in buckets. (This is the in-repo tracking store; see `SEAMAP.md` §Tracking.)
Checkbox marks status: `[ ]` backlog/next, `[~]` started, `[x]` done, `[!]` standing.
A trailing `←` comment carries `mountain:`, `priority:`, `tag:`, `standing`.

## In progress

## Next

- [ ] Eyeball a trace in the Honeycomb UI (team `modernity`: env `local` and env `cynditaylor-com-bot`, `WHERE service.name = "trainer-agent"`) ← Safe Harbor; priority: high
  - Prod telemetry is deployed and Boswell exported our span with no errors (local + prod pipes both proven). This is the final visual confirmation — can't be done in-session (no `modernity` MCP). See `notes/telemetry.md`.
- [ ] Verify warm-VM batching delivers end-of-session spans without per-invoke flush; if so, drop the flush to protect chat latency ← Safe Harbor; priority: medium
- [ ] Add an authed web endpoint — open endpoint + bearer-token validation (shared secret with my app) ← mountain: Deployed & wired up; priority: medium
- [ ] Wire my app to invoke the agent (InvokeAgentRuntime with a stable runtimeSessionId) and show the reply ← mountain: Deployed & wired up; priority: medium

## Backlog

- [ ] Consider adding local testing to the Safe Harbor definition in `SEAMAP.md` ← priority: low
  - Surfaced 2026-06-24 while building the Dockerfile + smoke harness. The harbor (a resting *state*) is currently just "we can see the agent working in Honeycomb". Question: should the bar also reflect that we can test the agent locally across the layers (`notes/local-testing-advice.md`) *before* trusting a deploy — i.e. "works locally" genuinely predicts "works in cloud"? Decide whether that's a Safe-Harbor property or just a working habit; edit the `## Safe Harbor` section if so.

## Owners
