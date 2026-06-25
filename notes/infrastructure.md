# Infrastructure — Trainer Agent

Everything this project touches in AWS. Append as we provision; this is the
durable record (Jessitron works across multiple computers).

## AWS account & profile

- **Profile**: `jessitron-sandbox`. On this computer that is `AWS_PROFILE=sandbox`
  (run every `aws`/deploy command with `AWS_PROFILE=sandbox`, or export it).
- **Account**: `414852377253`
- **Region**: `us-west-2` (the `sandbox` profile's configured region).
- Identity confirmed 2026-06-24 via `aws sts get-caller-identity`:
  assumed-role `OrganizationAccountAccessRole`.

## What this is

The **Trainer Agent**: it trains `jessitron/mtg-deck-shuffler` to give better
in-game recommendations. A single-purpose coding agent on **Bedrock AgentCore
Runtime** that chats with a human (via another app), implements a coding task,
and opens a PR. See `design/architecture.md`.

## How to (re)provision

Everything below is created by **`scripts/deploy.sh`** (build arm64 → push to ECR
→ ensure IAM role → create/update AgentCore runtime → wait for READY). It is
idempotent and re-runnable; it is the source of truth. IAM policy docs live in
`scripts/aws/`. Smoke the deployed runtime with `scripts/cloud-smoke.sh`.

**Region is pinned to `us-west-2` inside the scripts.** Do not rely on the shell's
`AWS_REGION`/`AWS_DEFAULT_REGION` — this machine defaults to `us-east-1`, and on the
first deploy that silently created resources in the wrong region (the runtime's
trust-policy `SourceArn` is pinned to `us-west-2`, so a us-east-1 runtime failed
role validation). The scripts now `export AWS_REGION=us-west-2` to force agreement.

## Provisioned resources

Created 2026-06-24 in **us-west-2**, account `414852377253`, profile `sandbox`.

| Resource | Type | Name / ARN | Notes |
|----------|------|------------|-------|
| ECR repo | ECR | `414852377253.dkr.ecr.us-west-2.amazonaws.com/trainer-agent` | scanOnPush=true; holds the arm64 image, tagged by git sha + `latest` |
| Execution role | IAM (global) | `arn:aws:iam::414852377253:role/trainer-agent-agentcore-runtime` | trust: `bedrock-agentcore.amazonaws.com` (SourceArn pinned us-west-2); inline policy `trainer-agent-runtime-permissions` (ECR pull, logs, X-Ray, Bedrock invoke, workload token, **GitHub PAT read**) |
| AgentCore runtime | Bedrock AgentCore | `arn:aws:bedrock-agentcore:us-west-2:414852377253:runtime/trainer_agent-VyiY9TFdtC` (id `trainer_agent-VyiY9TFdtC`) | name `trainer_agent`; `networkMode=PUBLIC`, `serverProtocol=HTTP`; container artifact from the ECR image |
| GitHub PAT secret | Secrets Manager | `trainer-agent/github-pat` (`…-VzKllL`) | fine-grained PAT for `jessitron/mtg-deck-shuffler` (Contents+PRs+Issues r/w); read at runtime by the agent (`src/agent/github_auth.py`) for clone/push/`open_pr`/`request_app_change`; local fallback is `.env`'s `GITHUB_TOKEN`. Created 2026-06-25 (JES-106). |

Invoke with `aws bedrock-agentcore invoke-agent-runtime` (data plane); the
`runtimeSessionId` must be **≥ 33 chars**. Verified 2026-06-24:
`{"message": "..."}` → `{"reply": "hi", "status": "chatting"}`.

**GitHub PAT secret** (created 2026-06-25, JES-106). The token value never goes
through the shell history or chat — pasted into a hidden prompt:

```bash
read -rs PAT && AWS_PROFILE=sandbox aws secretsmanager create-secret \
  --region us-west-2 --name trainer-agent/github-pat --secret-string "$PAT"; unset PAT
```

Read permission is the `GitHubPATSecretRead` statement in
`scripts/aws/permissions-policy.json` (scoped to `trainer-agent/github-pat-*`),
applied to the execution role by `scripts/deploy.sh`. Verify the whole path
(fetch + git wiring, no token printed) with
`AWS_PROFILE=sandbox uv run --no-sync python scripts/github-auth-smoke.py`.
Rotate by storing a new PAT version; the agent reads the current version each
cold start.

### Teardown

```
aws bedrock-agentcore-control delete-agent-runtime --region us-west-2 --agent-runtime-id trainer_agent-VyiY9TFdtC
aws iam delete-role-policy --role-name trainer-agent-agentcore-runtime --policy-name trainer-agent-runtime-permissions
aws iam delete-role --role-name trainer-agent-agentcore-runtime
aws ecr delete-repository --repository-name trainer-agent --region us-west-2 --force
aws secretsmanager delete-secret --secret-id trainer-agent/github-pat --region us-west-2 --force-delete-without-recovery
```

## Front door — authed Lambda + public Function URL

Created 2026-06-24 in **us-west-2**, account `414852377253`, profile `sandbox`,
by **`scripts/deploy-frontdoor.sh`** (idempotent; the source of truth). The app
POSTs JSON with a shared **bearer** to a public Function URL; the Lambda validates
it and proxies to `InvokeAgentRuntime` via SigV4. Smoke: `scripts/frontdoor-smoke.sh`.

**Fetch the bearer token** (what `INTERFACE.md` points consumers here for):

```bash
aws secretsmanager get-secret-value \
  --profile sandbox --region us-west-2 \
  --secret-id trainer-agent/frontdoor-bearer \
  --query SecretString --output text
```

| Resource | Type | Name / ARN | Notes |
|----------|------|------------|-------|
| Bearer secret | Secrets Manager | `trainer-agent/frontdoor-bearer` (`…-CCVd4Y`) | shared token the app presents; random `openssl rand -hex 32`; read at runtime by the Lambda |
| Lambda role | IAM (global) | `arn:aws:iam::414852377253:role/trainer-agent-frontdoor-lambda` | `AWSLambdaBasicExecutionRole` (logs) + inline `trainer-agent-frontdoor-permissions` (`InvokeAgentRuntime` on the runtime, `GetSecretValue` on the bearer) |
| Front-door Lambda | Lambda | `trainer-agent-frontdoor` | python3.13 / **arm64 / 128MB** / timeout 300s; zip-packaged (`frontdoor/`); `service.name=trainer-agent-frontdoor` |
| Function URL | Lambda Function URL | `https://3zpl56dwi54putsdjtecwnyqim0sdjmh.lambda-url.us-west-2.on.aws/` | `AuthType=NONE` (public); the Lambda validates the bearer in code |

### ⚠️ Gotcha — a public Function URL needs TWO permission statements

As of Oct 2025, `lambda:InvokeFunctionUrl` alone is **not** enough for an
`AuthType=NONE` URL — you also need `lambda:InvokeFunction` granted via
`--invoked-via-function-url`. Without the second statement the URL gate returns a
silent **403 `AccessDeniedException`** and the Lambda never runs (no CloudWatch
logs to debug from). `deploy-frontdoor.sh` adds both. Ref:
<https://www.honeycomb.io/blog/running-opentelemetry-collector-lambda>

### ⚠️ Gotcha — AgentCore forwards only `baggage`, not the trace params

`InvokeAgentRuntime` takes `traceParent`/`traceState`/`baggage` params, but
AgentCore forwards **only `baggage`** to the container as a request header
(`context.request_headers`) — it consumes `traceParent`/`traceState` for its own
internal trace linkage. So W3C trace context for *our* agent span rides in the
invoke **payload** (`traceparent`/`tracestate`), and the agent extracts it there.
Proven end-to-end: one trace spans test-client → frontdoor → agent.

### ⚠️ Gotcha — `deploy.sh` tags by HEAD sha; warm VMs serve the old image

Two deploy traps we hit: (1) `deploy.sh` tags the image with
`git rev-parse --short HEAD`, so **uncommitted** changes reuse the same tag and
may not redeploy cleanly — commit before deploying. (2) AgentCore keeps a
**warm microVM per session**; reusing a `runtimeSessionId` after a redeploy can
hit the *old* image. Use a fresh `session_id` to force the new version (the
smoke/propagation scripts accept `SESSION_ID`).

### Front-door teardown

```
aws lambda delete-function-url-config --function-name trainer-agent-frontdoor --region us-west-2
aws lambda delete-function --function-name trainer-agent-frontdoor --region us-west-2
aws iam detach-role-policy --role-name trainer-agent-frontdoor-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role-policy --role-name trainer-agent-frontdoor-lambda --policy-name trainer-agent-frontdoor-permissions
aws iam delete-role --role-name trainer-agent-frontdoor-lambda
aws secretsmanager delete-secret --secret-id trainer-agent/frontdoor-bearer --region us-west-2 --force-delete-without-recovery
```

### Front-door test stub (private ECR)

A validating stand-in for the front door, for mtg-deck-shuffler's local/CI testing.
Published by **`scripts/publish-stub.sh`**; built from `frontdoor/Dockerfile.stub`
(stdlib-only `frontdoor/stub.py` + the shared `frontdoor/contract.py`). Enforces the
same request contract as prod, returns canned replies. Usage doc:
[`INTERFACE.md`](../INTERFACE.md) §"Local testing — the stub".

| Resource | Type | Name / URI | Notes |
|----------|------|------------|-------|
| Stub image | ECR (**private**) | `414852377253.dkr.ecr.us-west-2.amazonaws.com/trainer-agent-frontdoor-stub` | multi-arch (amd64+arm64), tagged by git sha + `latest`; pull needs AWS access to this account; `docker run -p 8080:8080 -e STUB_BEARER=… <uri>:latest` |

Teardown: `aws ecr delete-repository --repository-name trainer-agent-frontdoor-stub --region us-west-2 --force`

## Still planned (from TODO.md, mountain: "Deployed & wired up")

- **Secrets Manager secret** holding the fine-grained GitHub PAT (fetched at
  runtime, never baked into the image) — needed once the agent opens PRs.
- **Wire my app** to POST the front-door Function URL with the bearer + a stable
  `session_id` (and a `traceparent` to continue its trace).

(The IAM execution-role policy already grants Bedrock `InvokeModel` and X-Ray, so
the real agent loop and OTel can land without a permissions change.)
