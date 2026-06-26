"""Per-session workspace: clone the target repo and load its brief.

On the first invoke of a session the agent needs a working copy of
``jessitron/mtg-deck-shuffler`` and the app's standing instructions for what it
wants done. Both live here:

- **Clone** the repo into a session-scoped dir on first use; **reuse** it on
  later invokes (AgentCore keeps the microVM warm with session affinity, so the
  clone and any work-in-progress survive between turns).
- **Load** ``trainer-agent/instructions.md`` from the clone — the app owns this
  file (see ``INTERFACE.md``); *this* repo only knows its path.

Anything that goes wrong here is a :class:`WorkspaceError`, which the caller turns
into an honest ``status: error`` reply rather than guessing past it.

Test seam: the repo URL comes from ``TRAINER_REPO_URL`` (default: the GitHub
HTTPS URL) and the root dir from ``TRAINER_WORKSPACE_ROOT`` (default
``/tmp/trainer-sessions``), so tests can clone a local fixture offline.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from opentelemetry import trace

from agent.github_auth import configure_git_credentials

TARGET_REPO = "jessitron/mtg-deck-shuffler"
DEFAULT_REPO_URL = f"https://github.com/{TARGET_REPO}.git"
INSTRUCTIONS_RELPATH = "trainer-agent/instructions.md"

_tracer = trace.get_tracer("agent.workspace")


class WorkspaceError(Exception):
    """A workspace setup problem the agent must surface honestly (status: error)
    instead of guessing past."""


def workspace_root() -> Path:
    return Path(os.environ.get("TRAINER_WORKSPACE_ROOT", "/tmp/trainer-sessions"))


def repo_url() -> str:
    return os.environ.get("TRAINER_REPO_URL", DEFAULT_REPO_URL)


def _safe_session_dir(session_id: str) -> str:
    # session_id is >= 33 chars; keep it filesystem-safe without losing identity.
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)


def session_repo_dir(session_id: str) -> Path:
    return workspace_root() / _safe_session_dir(session_id) / "repo"


def ensure_clone(session_id: str) -> Path:
    """Return the session's repo dir, cloning on first use and reusing it after.

    Reuse is detected by an existing ``.git`` dir — so turn 2+ in a warm microVM
    skips the clone and keeps any work-in-progress. Raises :class:`WorkspaceError`
    on a missing session id or a failed clone.
    """
    if not session_id:
        raise WorkspaceError("no session_id; cannot set up a workspace")

    repo_dir = session_repo_dir(session_id)
    if (repo_dir / ".git").is_dir():
        return repo_dir  # warm clone — reuse it

    url = repo_url()
    # Authenticate only for real GitHub HTTPS (so a private repo clones and a
    # later push works). A local/file fixture URL needs no credentials.
    if url.startswith("https://github.com"):
        configure_git_credentials()

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    if repo_dir.exists():
        shutil.rmtree(repo_dir)  # clear a partial/aborted clone

    with _tracer.start_as_current_span("agent.git_clone") as span:
        span.set_attribute("repo", TARGET_REPO)
        span.set_attribute("session.id", session_id)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(repo_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise WorkspaceError("git is not installed in this environment") from exc
        except subprocess.CalledProcessError as exc:
            # stderr carries the URL but never the token (the credential helper
            # supplies that out of band), so it's safe to surface.
            span.set_attribute("git.clone.returncode", exc.returncode)
            detail = (exc.stderr or "").strip()[:500]
            raise WorkspaceError(f"git clone failed: {detail}") from exc
        span.set_attribute("workspace.dir", str(repo_dir))
    return repo_dir


def load_instructions(repo_dir) -> str:
    """Read the app's brief from ``trainer-agent/instructions.md``.

    Missing or empty is a :class:`WorkspaceError`: we won't guess what the app
    wants of us — that's dishonest and the user should know the brief is absent.
    """
    path = Path(repo_dir) / INSTRUCTIONS_RELPATH
    if not path.is_file():
        raise WorkspaceError(
            f"{INSTRUCTIONS_RELPATH} not found in {TARGET_REPO}; "
            "the app must add it (see INTERFACE.md)."
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise WorkspaceError(f"{INSTRUCTIONS_RELPATH} is empty in {TARGET_REPO}.")
    return text
