# Trainer Agent image for Amazon Bedrock AgentCore Runtime.
#
# AgentCore requires linux/arm64 and a container that serves POST /invocations
# and GET /ping on port 8080 — which BedrockAgentCoreApp.run() does.
#
# ALWAYS build for linux/arm64 (pass --platform at build time, not in FROM):
#   docker build --platform linux/arm64 -t trainer-agent:local .
# Native on Apple Silicon (no emulation). scripts/smoke-container.sh and the
# deploy/build scripts always pass --platform linux/arm64.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# git + gh: the agent clones jessitron/mtg-deck-shuffler and pushes branches
# (git), and opens PRs / files issues (gh, via open_pr / request_app_change).
# gh comes from GitHub's apt repo. One layer, cached unless this line changes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl gnupg \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Install dependencies first so this layer caches unless the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the application code, and install the project itself (for the `agent` script).
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8080

CMD ["uv", "run", "--no-sync", "agent"]
