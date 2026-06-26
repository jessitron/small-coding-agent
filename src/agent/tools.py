"""The agent's coding tools, scoped to one session's repo workspace.

Strands core ships no file/shell tools, so we define our own — which is better
here anyway: each tool is *closed over the session's repo dir* and refuses paths
that escape it, giving us the workspace-scoping the design calls for without a
process-global ``chdir`` (unsafe in a long-lived server). ``run_shell`` is how
the agent runs builds, tests, ``git``, and the repo's own ``trainer-agent/``
helper scripts.

``make_workspace_tools(repo_dir)`` returns a fresh list of tools bound to that
dir; the loop builds them per invoke against the session's clone.
"""

import subprocess
from pathlib import Path

from strands import tool

SHELL_TIMEOUT_SECONDS = 120
_MAX_OUTPUT_CHARS = 6000


def make_workspace_tools(repo_dir):
    workspace = Path(repo_dir).resolve()

    def _resolve(rel: str) -> Path:
        p = (workspace / rel).resolve()
        if p != workspace and workspace not in p.parents:
            raise ValueError(f"path {rel!r} escapes the workspace")
        return p

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
        entries = sorted(
            e.name + ("/" if e.is_dir() else "") for e in p.iterdir()
        )
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

    return [read_file, write_file, list_dir, run_shell]
