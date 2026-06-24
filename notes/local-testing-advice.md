# Advice for testing a Strands-on-AgentCore agent locally

This advice comes from the agent that works on cyndibot, another Strands agent I maintain:

You're building a Strands agent that runs on AWS AgentCore. AgentCore deploys are
slow and the cloud is a hostile debugger. The single most important habit: **find
every bug at the lowest layer that can reproduce it.** Below are the layers, cheapest
and fastest first. Build the ability to test at each one _before_ you need it.

## The deployment-distance principle

Each step away from your local process — into a container, into the cloud — adds
minutes to your feedback loop and removes your debugger. So:

- A tool bug found as a plain function call: **seconds**, real stack trace.
- The same bug found in the deployed runtime: **minutes**, CloudWatch archaeology.

Every layer you can push a bug _down_ into is a multiplier on your iteration speed.
Don't reach for a deploy to test something a function call could have caught.

## Layer 1 — Tool logic, no LLM (highest ROI, build this first)

Most agent bugs are not in the model. They're in your **tools**: parsing inputs,
talking to external services (S3, git, an API, email), serializing results. These
are deterministic and fast.

Write small smoke scripts that call each tool directly with a fixed input and assert
the result. No Bedrock, no tokens, no nondeterminism. This is the cheapest, most
valuable testing you have, and the easiest to skip. Don't skip it.

- One script per side-effecting tool (read X, write X, push X, send X).
- Make them safe to run repeatedly (throwaway branches, idempotent writes).
- These double as living documentation of how each tool is called.

## Layer 2 — Full LLM loop, in your own process (no container)

Run the _real_ Strands agent against _real_ Bedrock, but in your own Python process
with a synthetic input. This is where you observe **behavior**: does the model chain
your tools in the right order? Does it ever call the tool you expect? Does it obey
the system prompt?

- You get a real debugger and real stack traces.
- Fast cycle — no image build between edits.
- Use a couple of canned inputs that exercise the interesting paths (happy path,
  an attachment/binary path, an error path).
- This catches the bugs unit tests can't: "the model never calls `commit`,"
  "it misreads the instructions," "it loops."

## Layer 3 — The container, locally

Now test the **packaging**, not the logic. Build the image (match AgentCore's
architecture — arm64), run it locally, and hit the same HTTP surface AgentCore
calls (`/ping`, `/invocations`). Mount your AWS creds read-only.

This catches the class of bug that only appears once code is wrapped in HTTP +
Docker: entrypoint/secret-fetch failures, missing env vars, arch mismatches,
request/response shape drift from what AgentCore sends. You find them in one local
`docker run` instead of a deploy.

## Layer 4 — Telemetry, locally, with the SAME config as cloud

Instrument with OpenTelemetry from day one — an agent's reasoning is invisible
otherwise. Then run a local OTel collector using the **exact same collector config
you deploy to cloud**, pointed at a separate "local" environment in your backend.

Two payoffs:

1. You debug the agent's full reasoning — every LLM turn, every tool call — as a
   trace, on your laptop.
2. Because the trace _shape_ is identical local vs. cloud, the dashboards and
   queries you build locally work unchanged against production. "Works locally"
   actually predicts "works in cloud" for the observability layer, because you're
   not shipping a different pipeline than you tested.

## Layer 5 — Cloud smoke (the thin top)

Keep exactly one script that invokes the deployed runtime end-to-end, for after a
deploy. It confirms wiring (IAM, networking, the dispatcher in front of the agent) —
_not_ logic, which you already proved below. If a logic bug reaches this layer,
that's a signal you were missing a test one layer down; add it there.

## Working habits that make this pay off

- **Scripts, not herefiles.** Give each test a name and check it in. They're the
  test suite and the runbook at once. Make them directly executable.
- **Build the harness before the feature.** A new tool ships with its Layer-1
  smoke script in the same change.
- **After any run that emits traces, grab the trace URL.** Click through to confirm
  what actually happened — don't trust "it returned 200."
- **Fail loud, no fallbacks.** A tool that swallows an error and returns a plausible
  result will fool the model and you. Raise.
- **Push bugs down.** When something breaks in cloud, the fix isn't just the fix —
  it's also a test at the lowest layer that would've caught it.
