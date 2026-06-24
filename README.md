# small-coding-agent

A single-purpose coding agent on **Amazon Bedrock AgentCore Runtime**. It chats
with a human, implements a coding task on `jessitron/mtg-deck-shuffler`, and
opens a PR.

See [`design/architecture.md`](design/architecture.md) for the full design and
the invoke contract.

## Architecture

```
  ┌────────────────────────────┐
  │     MTG Deck Shuffler UI    │   chat in the browser
  └──────────────┬─────────────┘
                 │  websocket
                 ▼
  ┌────────────────────────────┐
  │   MTG Deck Shuffler backend │   owns the chat + conversation history
  └──────────────┬─────────────┘
                 │  HTTPS (bearer token)
                 ▼
  ┌────────────────────────────┐
  │    Lambda (HTTP endpoint)   │   fulfills the endpoint, invokes AgentCore
  └──────────────┬─────────────┘
                 │  InvokeAgentRuntime (runtimeSessionId)
                 ▼
  ┌────────────────────────────┐
  │        Trainer Agent        │   Strands agent: gathers requirements,
  │     (AgentCore Runtime)     │   codes on a branch, opens the PR
  └──────────────┬─────────────┘
                 │  git push + gh pr create
                 ▼
  ┌────────────────────────────┐
  │           GitHub            │   jessitron/mtg-deck-shuffler → PR
  └────────────────────────────┘
```

| Hop | How |
| --- | --- |
| UI → backend | Websocket; the backend owns the chat UI and the conversation history. |
| backend → Lambda | HTTPS to an endpoint fulfilled by a Lambda, authenticated with a bearer token. |
| Lambda → Trainer Agent | `InvokeAgentRuntime`, once per user message, carrying a stable `runtimeSessionId`. |
| Trainer Agent → GitHub | Implements on a branch, then `git push` + `gh pr create`; the PR link flows back up the chain. |
