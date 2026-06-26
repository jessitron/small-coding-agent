"""The Trainer Agent's one loop: assemble context, run a Strands turn, reply.

Per the design split (``design/architecture.md``): *this* repo owns **how to use
the tools** (the system-prompt header below); the *target* repo owns **what is
wanted of us** (``trainer-agent/instructions.md``, loaded into the prompt). Each
turn the agent reasons over the brief + the user's message + the current game
state, acts with its workspace-scoped tools, and replies.

Conversation is persisted per ``session_id`` with Strands' ``FileSessionManager``
into the session workspace, so turn 2+ resumes the same conversation (and is what
the JES-109 ``seq`` check reads to detect a lost session).
"""

import json
import os
from pathlib import Path

from opentelemetry import trace
from strands import Agent
from strands.session import FileSessionManager

from agent.tools import make_workspace_tools
from agent.workspace import (
    WorkspaceError,
    ensure_clone,
    load_instructions,
    session_repo_dir,
)

AGENT_ID = "trainer-agent"

# How to use the tools — the half of the brief this repo owns. The other half
# (what to actually do) comes from the app's trainer-agent/instructions.md.
SYSTEM_PROMPT_HEADER = """\
You are the Trainer Agent, a single-purpose coding agent. You help improve the app
jessitron/mtg-deck-shuffler by chatting with a person and, when you have a concrete
change, opening a pull request against that repo.

You are working inside a clone of that repo. Your tools are scoped to it:
- read_file(path) / write_file(path, content) — paths are relative to the repo root.
- list_dir(path) — see what's there.
- run_shell(command) — run builds, tests, git, and the repo's own trainer-agent/
  helper scripts. Prefer the repo's scripts when the instructions point you at them.

Work in one loop: gather what you need, make the change on a branch, and explain
what you did. If you are missing information you cannot get from the repo or the
game state, ask the user a clear question instead of guessing.

Below are the app's own instructions for what it wants of you. Follow them.
"""


def _system_prompt(instructions: str) -> str:
    return f"{SYSTEM_PROMPT_HEADER}\n\n## The app's instructions\n\n{instructions}\n"


def _session_storage_dir(session_id: str) -> str:
    # Sit beside the repo clone, under the same session dir.
    return str(session_repo_dir(session_id).parent / "agent-session")


def _turns_file(session_id: str) -> Path:
    return session_repo_dir(session_id).parent / "turns_seen"


def _read_turns_seen(session_id: str) -> int:
    """How many turns this session has completed, per its on-disk counter. A fresh
    microVM (expired session) has no file -> 0, which is exactly how a lost session
    is detected against the client's seq."""
    try:
        return int(_turns_file(session_id).read_text())
    except (FileNotFoundError, ValueError):
        return 0


def _record_turn(session_id: str, turns_seen: int) -> None:
    f = _turns_file(session_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(turns_seen + 1))


def _build_agent(session_id: str, repo_dir, instructions: str) -> Agent:
    storage_dir = _session_storage_dir(session_id)
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    session_manager = FileSessionManager(
        session_id=session_id, storage_dir=storage_dir
    )
    kwargs = dict(
        agent_id=AGENT_ID,
        system_prompt=_system_prompt(instructions),
        tools=make_workspace_tools(repo_dir),
        session_manager=session_manager,
    )
    model_id = os.environ.get("TRAINER_MODEL_ID")
    if model_id:
        kwargs["model"] = model_id  # else Strands' default Bedrock model
    return Agent(**kwargs)


def _turn_input(message: str, state) -> str:
    if state is None:
        return message
    rendered = json.dumps(state, indent=2, ensure_ascii=False)
    return f"{message}\n\n## Current game state\n```json\n{rendered}\n```"


def run_turn(payload, session_id) -> dict:
    """Run one chat turn. Returns the response dict ``{reply, status, pr_url?}``.

    Failures come back as an honest ``status: error`` — never a guess:
    - **context loss** — the client's ``seq`` doesn't match the turns this session
      has actually handled (a fresh/expired microVM lost the game state);
    - **workspace** — no session, clone failed, or the brief is missing;
    - **model** — the agent turn itself raised.
    """
    span = trace.get_current_span()
    message = payload.get("message", "")
    seq = payload.get("seq")

    # 1. Context-loss check (only when the client declares a seq). If the session
    #    is fresh, turns_seen is 0 and any seq > 1 means we lost the game state.
    turns_seen = _read_turns_seen(session_id) if session_id else 0
    if seq is not None and seq != turns_seen + 1:
        span.set_attribute("agent.context_lost", True)
        span.set_attribute("agent.seq_received", seq)
        span.set_attribute("agent.seq_expected", turns_seen + 1)
        return {
            "reply": (
                "I've lost the context for this conversation — I expected message "
                f"#{turns_seen + 1} but received #{seq}, which means the session "
                "expired and the game state is gone. Please start a new conversation."
            ),
            "status": "error",
        }

    # 2. Workspace: clone (first turn) + load the app's brief.
    try:
        repo_dir = ensure_clone(session_id)
        instructions = load_instructions(repo_dir)
    except WorkspaceError as exc:
        return {
            "reply": (
                f"I can't get set up to help: {exc} "
                "Please start a new conversation once that's resolved."
            ),
            "status": "error",
        }

    # 3. Run the turn. Advance the counter only on success, so a retry with the
    #    same seq still lines up.
    try:
        agent = _build_agent(session_id, repo_dir, instructions)
        result = agent(_turn_input(message, payload.get("state")))
    except Exception as exc:  # keep the contract: always {reply, status}
        span.record_exception(exc)
        return {
            "reply": f"The agent hit an error while working: {exc}",
            "status": "error",
        }

    _record_turn(session_id, turns_seen)
    return {"reply": str(result), "status": "chatting"}
