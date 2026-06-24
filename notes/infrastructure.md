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
| Execution role | IAM (global) | `arn:aws:iam::414852377253:role/trainer-agent-agentcore-runtime` | trust: `bedrock-agentcore.amazonaws.com` (SourceArn pinned us-west-2); inline policy `trainer-agent-runtime-permissions` (ECR pull, logs, X-Ray, Bedrock invoke, workload token) |
| AgentCore runtime | Bedrock AgentCore | `arn:aws:bedrock-agentcore:us-west-2:414852377253:runtime/trainer_agent-VyiY9TFdtC` (id `trainer_agent-VyiY9TFdtC`) | name `trainer_agent`; `networkMode=PUBLIC`, `serverProtocol=HTTP`; container artifact from the ECR image |

Invoke with `aws bedrock-agentcore invoke-agent-runtime` (data plane); the
`runtimeSessionId` must be **≥ 33 chars**. Verified 2026-06-24:
`{"message": "..."}` → `{"reply": "hi", "status": "chatting"}`.

### Teardown

```
aws bedrock-agentcore-control delete-agent-runtime --region us-west-2 --agent-runtime-id trainer_agent-VyiY9TFdtC
aws iam delete-role-policy --role-name trainer-agent-agentcore-runtime --policy-name trainer-agent-runtime-permissions
aws iam delete-role --role-name trainer-agent-agentcore-runtime
aws ecr delete-repository --repository-name trainer-agent --region us-west-2 --force
```

## Still planned (from TODO.md, mountain: "Deployed & wired up")

- **Bearer-token auth**: the runtime is currently invoked with IAM/SigV4
  (default). Add an authorizer so the calling app uses a shared bearer secret
  (`--authorizer-configuration` on the runtime).
- **Secrets Manager secret** holding the fine-grained GitHub PAT (fetched at
  runtime, never baked into the image) — needed once the agent opens PRs.
- **Wire my app** to invoke the runtime with a stable `runtimeSessionId`.

(The IAM execution-role policy already grants Bedrock `InvokeModel` and X-Ray, so
the real agent loop and OTel can land without a permissions change.)
