"""The agent's tools, scoped to one session's repo workspace.

Two kinds:

- **Coding tools** (``read_file``/``write_file``/``list_dir``/``run_shell``) —
  each closed over the session's repo dir and refusing paths that escape it, so
  the agent is workspace-scoped without a process-global ``chdir`` (unsafe in a
  long-lived server). ``run_shell`` runs builds, tests, ``git``, and the repo's
  own ``trainer-agent/`` helper scripts.
- **Collaboration tools** — ``open_pr`` (agent → app: here's the change) and
  ``request_app_change`` (agent → app: here's what I need to do better, filed as a
  GitHub issue). Both shell out to ``gh`` with the PAT already in the environment
  (``agent.github_auth``).

``make_workspace_tools(repo_dir, session_id)`` returns a fresh list bound to that
session; the loop builds them per invoke.
"""

import re
import subprocess
from pathlib import Path

from opentelemetry import trace
from strands import tool

from agent.workspace import TARGET_REPO, session_repo_dir

SHELL_TIMEOUT_SECONDS = 120
GH_TIMEOUT_SECONDS = 60
_MAX_OUTPUT_CHARS = 6000

_PR_URL_RE = re.compile(r"https://github\.com/\S+/pull/\d+")
_ISSUE_URL_RE = re.compile(r"https://github\.com/\S+/issues/\d+")


def pr_marker_path(session_id: str) -> Path:
    """File where ``open_pr`` records the PR URL, so the loop can report it as
    ``pr_url`` + ``status: done``."""
    return session_repo_dir(session_id).parent / "pr_url"


def _branch_for(session_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", session_id).strip("-")[-40:]
    return f"trainer-agent/{slug or 'change'}"


def make_workspace_tools(repo_dir, session_id):
    workspace = Path(repo_dir).resolve()

    def _resolve(rel: str) -> Path:
        p = (workspace / rel).resolve()
        if p != workspace and workspace not in p.parents:
            raise ValueError(f"path {rel!r} escapes the workspace")
        return p

    def _git(*args, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=check,
        )

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 text file from the repo. `path` is relative to the repo root."""
        return _resolve(path).read_text(encoding="utf-8")

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a UTF-8 text file in the repo. `path` is relative to the repo root."""
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} bytes)"

    @tool
    def list_dir(path: str = ".") -> str:
        """List the entries at `path` (relative to the repo root). Directories end with '/'."""
        p = _resolve(path)
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        return "\n".join(entries) if entries else "(empty)"

    @tool
    def run_shell(command: str) -> str:
        """Run a shell command in the repo workspace; returns the exit code and combined
        stdout/stderr. Use for builds, tests, git, and the repo's trainer-agent helper scripts."""
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=SHELL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"exit=timeout (>{SHELL_TIMEOUT_SECONDS}s)"
        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > _MAX_OUTPUT_CHARS:
            out = "...(truncated)...\n" + out[-_MAX_OUTPUT_CHARS:]
        return f"exit={proc.returncode}\n{out}"

    @tool
    def open_pr(title: str, body: str = "") -> str:
        """Commit the current changes onto a branch, push, and open a pull request on
        jessitron/mtg-deck-shuffler. Call this once you have a complete, reviewable change.
        Returns the PR URL. Safe to call again to push follow-up commits to the same PR."""
        branch = _branch_for(session_id)
        _git("checkout", "-B", branch)
        _git("add", "-A")
        if _git("status", "--porcelain").stdout.strip():
            _git("commit", "-m", title)
        push = _git("push", "-u", "origin", branch, check=False)
        if push.returncode != 0:
            return f"push failed: {(push.stderr or '').strip()[-500:]}"

        create = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body or title,
             "--head", branch],
            cwd=str(workspace), capture_output=True, text=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
        out = (create.stdout or "") + (create.stderr or "")
        match = _PR_URL_RE.search(out)
        if not match:
            # A PR may already exist for this branch; ask gh for its URL.
            view = subprocess.run(
                ["gh", "pr", "view", branch, "--json", "url", "-q", ".url"],
                cwd=str(workspace), capture_output=True, text=True,
                timeout=GH_TIMEOUT_SECONDS, check=False,
            )
            match = _PR_URL_RE.search(view.stdout or "")
        if not match:
            return f"could not open PR: {out.strip()[-500:]}"

        url = match.group(0)
        pr_marker_path(session_id).write_text(url)
        trace.get_current_span().set_attribute("pr.url", url)
        return f"opened PR: {url}"

    @tool
    def request_app_change(title: str, body: str) -> str:
        """File a GitHub issue on jessitron/mtg-deck-shuffler to request a change to YOUR
        inputs — e.g. data you need added to the request `state`, or a clarification to the
        brief. Use when you can't get what you need from the repo or the game state. Returns
        the issue URL. Write it to be acted on cold: what you were doing, what's missing, what
        you want instead."""
        create = subprocess.run(
            ["gh", "issue", "create", "--repo", TARGET_REPO,
             "--title", title, "--body", body],
            capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS,
        )
        out = (create.stdout or "") + (create.stderr or "")
        match = _ISSUE_URL_RE.search(out)
        if not match:
            return f"could not file issue: {out.strip()[-500:]}"
        url = match.group(0)
        trace.get_current_span().set_attribute("issue.url", url)
        return f"filed issue: {url}"

    return [read_file, write_file, list_dir, run_shell, open_pr, request_app_change]
