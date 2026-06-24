# small-coding-agent

A single-purpose coding agent on **Amazon Bedrock AgentCore Runtime**. It chats
with a human, implements a coding task on `jessitron/mtg-deck-shuffler`, and
opens a PR.

See [`design/architecture.md`](design/architecture.md) for the full design and
the invoke contract.

## Architecture

```mermaid
flowchart TD
    UI["MTG Deck Shuffler UI<br/><i>chat in the browser</i>"]
    Backend["MTG Deck Shuffler backend<br/><i>owns the chat + conversation history</i>"]
    Lambda["Lambda<br/><i>fulfills the HTTP endpoint</i>"]
    Agent["Trainer Agent — AgentCore Runtime<br/><i>Strands agent: gathers requirements,<br/>codes on a branch, opens the PR</i>"]
    GitHub["GitHub<br/><i>jessitron/mtg-deck-shuffler → PR</i>"]

    UI -->|websocket| Backend
    Backend -->|HTTPS, bearer token| Lambda
    Lambda -->|InvokeAgentRuntime, runtimeSessionId| Agent
    Agent -->|git push + gh pr create| GitHub

    classDef inRepo fill:#cdeccd,stroke:#2e7d32,stroke-width:2px,color:#000;
    class Lambda,Agent inRepo;
```

> 🟩 Green nodes (**Lambda** and **Trainer Agent**) are what lives in this repo.
> The rest are external systems we talk to.

| Hop | How |
| --- | --- |
| UI → backend | Websocket; the backend owns the chat UI and the conversation history. |
| backend → Lambda | HTTPS to an endpoint fulfilled by a Lambda, authenticated with a bearer token. |
| Lambda → Trainer Agent | `InvokeAgentRuntime`, once per user message, carrying a stable `runtimeSessionId`. |
| Trainer Agent → GitHub | Implements on a branch, then `git push` + `gh pr create`; the PR link flows back up the chain. |
