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
