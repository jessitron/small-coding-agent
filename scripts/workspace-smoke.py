"""Offline smoke test for the per-session workspace (JES-107).

Builds local git fixture repos and exercises agent.workspace without network or
credentials, via the TRAINER_REPO_URL / TRAINER_WORKSPACE_ROOT test seams:

  - clone on first use, then REUSE on the second call (work-in-progress survives)
  - load_instructions returns the brief
  - missing instructions -> WorkspaceError
  - empty instructions   -> WorkspaceError

Run:  uv run --no-sync python scripts/workspace-smoke.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_fixture_repo(path: Path, instructions: str | None):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "Test")
    if instructions is not None:
        d = path / "trainer-agent"
        d.mkdir()
        (d / "instructions.md").write_text(instructions, encoding="utf-8")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "fixture")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["TRAINER_WORKSPACE_ROOT"] = str(tmp / "sessions")

        # Import after env is set so defaults don't get baked in.
        from agent import workspace
        from agent.workspace import WorkspaceError

        # --- happy path: clone + load -------------------------------------
        good = tmp / "good-repo"
        _make_fixture_repo(good, "Improve the recommendation. Run trainer-agent/cards.sh for detail.")
        os.environ["TRAINER_REPO_URL"] = str(good)

        sid = "session-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        repo_dir = workspace.ensure_clone(sid)
        assert (repo_dir / ".git").is_dir(), "clone should produce a .git dir"
        text = workspace.load_instructions(repo_dir)
        assert "recommendation" in text, "instructions should load"
        print("clone + load_instructions: OK")

        # --- reuse: a marker dropped in the clone must survive a 2nd call ---
        marker = repo_dir / "WORK_IN_PROGRESS"
        marker.write_text("x")
        repo_dir2 = workspace.ensure_clone(sid)
        assert repo_dir2 == repo_dir, "same session -> same dir"
        assert marker.is_file(), "warm clone must be reused, not re-cloned"
        print("reuse warm clone (work-in-progress survives): OK")

        # --- missing instructions -----------------------------------------
        bare = tmp / "bare-repo"
        _make_fixture_repo(bare, instructions=None)
        os.environ["TRAINER_REPO_URL"] = str(bare)
        sid2 = "session-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        rd = workspace.ensure_clone(sid2)
        try:
            workspace.load_instructions(rd)
            print("FAIL: missing instructions did not raise")
            sys.exit(1)
        except WorkspaceError:
            print("missing instructions -> WorkspaceError: OK")

        # --- empty instructions -------------------------------------------
        empty = tmp / "empty-repo"
        _make_fixture_repo(empty, instructions="   \n")
        os.environ["TRAINER_REPO_URL"] = str(empty)
        sid3 = "session-cccccccccccccccccccccccccccccccccc"
        rd3 = workspace.ensure_clone(sid3)
        try:
            workspace.load_instructions(rd3)
            print("FAIL: empty instructions did not raise")
            sys.exit(1)
        except WorkspaceError:
            print("empty instructions -> WorkspaceError: OK")

    print("PASS")


if __name__ == "__main__":
    main()
