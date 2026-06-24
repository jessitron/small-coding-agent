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

## Provisioned resources

_Nothing provisioned yet._ As of 2026-06-24 the agent runs only locally
(`uv run agent`, port 8080). This section gets a row per resource as we create
them — Bedrock AgentCore runtime, the agent's IAM execution role, the ECR repo
for the image, and the GitHub PAT in Secrets Manager.

| Resource | Type | Name / ARN | Notes |
|----------|------|------------|-------|
| _(none yet)_ | | | |

## Planned (from TODO.md, mountain: "Deployed & wired up")

- **ECR repository** for the agent image (deploy via our own Dockerfile, not the
  starter-toolkit CodeBuild path).
- **Bedrock AgentCore Runtime** hosting the image; invoked with
  `InvokeAgentRuntime(runtimeSessionId, {message})`.
- **IAM execution role** for the runtime (Bedrock model invoke + Secrets Manager
  read + CloudWatch/OTel egress).
- **Secrets Manager secret** holding the fine-grained GitHub PAT (fetched at
  runtime, never baked into the image).
- **Bearer-token auth**: an open web endpoint validated against a shared secret
  with the calling app.
