# TODO — small-coding-agent

Open work, in buckets. (This is the in-repo tracking store; see `SEAMAP.md` §Tracking.)
Checkbox marks status: `[ ]` backlog/next, `[~]` started, `[x]` done, `[!]` standing.
A trailing `←` comment carries `mountain:`, `priority:`, `tag:`, `standing`.

## In progress

## Next

- [ ] Scaffold the Python project (Strands Agents + `bedrock-agentcore`) with a minimal `BedrockAgentCoreApp` + `@app.entrypoint` that replies "hi" ← mountain: Deployed & wired up; priority: high
- [ ] Write the Dockerfile for the agent image (deploy via Dockerfile, not starter-toolkit CodeBuild) ← mountain: Deployed & wired up; priority: high
- [ ] Deploy the agent to Bedrock AgentCore Runtime ← mountain: Deployed & wired up; priority: high
- [ ] Add an authed web endpoint — open endpoint + bearer-token validation (shared secret with my app) ← mountain: Deployed & wired up; priority: medium
- [ ] Wire my app to invoke the agent (InvokeAgentRuntime with a stable runtimeSessionId) and show the reply ← mountain: Deployed & wired up; priority: medium

## Backlog

## Owners
