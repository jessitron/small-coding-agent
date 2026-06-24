"""Trainer Agent entrypoint for Amazon Bedrock AgentCore Runtime.

The Trainer Agent trains ``jessitron/mtg-deck-shuffler`` to give better in-game
recommendations: it chats with a human (through another app, over synchronous
HTTP), implements a coding task on a branch, and opens a PR.

This module is the minimal scaffold. It stands up the AgentCore harness and
replies "hi", proving the deploy pipe end to end. The Strands agent loop, GitHub
tools, and observability arrive in later landings (see TODO.md).

Run locally::

    uv run agent

then in another shell::

    curl -XPOST http://localhost:8080/invocations \
        -H 'Content-Type: application/json' \
        -d '{"message": "hello"}'

AgentCore serves the entrypoint at ``POST /invocations`` on port 8080, with a
health check at ``GET /ping``.
"""

from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    """Handle one chat turn.

    Request/response follow the invoke contract in ``design/architecture.md``:

        request:  {"message": "user's chat message"}
        response: {"reply": "...", "status": "chatting|coding|asking|done|error",
                   "pr_url": "https://github.com/.../pull/123"}

    ``runtimeSessionId`` is carried by AgentCore, not in the body.
    """
    _message = payload.get("message", "")
    return {"reply": "hi", "status": "chatting"}


def main():
    """Console-script entrypoint: start the AgentCore HTTP server."""
    app.run()


if __name__ == "__main__":
    main()
