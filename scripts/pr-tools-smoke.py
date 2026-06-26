"""Offline smoke for open_pr + request_app_change (JES-110, JES-111).

No network, no real GitHub: a fake `gh` on PATH stands in for the GitHub API, and
a local bare repo stands in for origin. This exercises the REAL git path
(branch -> commit -> push to origin) plus the tool's gh invocation and URL
parsing. The fake gh just prints the URLs gh would print.

Run:  uv run --no-sync python scripts/pr-tools-smoke.py
"""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

FAKE_GH = """\
#!/usr/bin/env bash
case "$1 $2" in
  "pr create") echo "https://github.com/jessitron/mtg-deck-shuffler/pull/123" ;;
  "pr view")   echo "https://github.com/jessitron/mtg-deck-shuffler/pull/123" ;;
  "issue create") echo "https://github.com/jessitron/mtg-deck-shuffler/issues/45" ;;
  *) echo "fake gh: $*" ;;
esac
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["TRAINER_WORKSPACE_ROOT"] = str(tmp / "sessions")

        # fake gh on PATH
        binv = tmp / "bin"
        binv.mkdir()
        gh = binv / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        os.environ["PATH"] = f"{binv}{os.pathsep}{os.environ['PATH']}"

        # source repo -> bare "remote"
        src = tmp / "src"
        src.mkdir()
        _git(src, "init", "-q", "-b", "main")
        _git(src, "config", "user.email", "t@e.com")
        _git(src, "config", "user.name", "T")
        (src / "trainer-agent").mkdir()
        (src / "trainer-agent" / "instructions.md").write_text("Do good work.\n")
        (src / "README.md").write_text("# App\n")
        _git(src, "add", "-A")
        _git(src, "commit", "-q", "-m", "init")
        remote = tmp / "remote.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(remote)], check=True)
        os.environ["TRAINER_REPO_URL"] = str(remote)

        from agent.tools import make_workspace_tools, pr_marker_path
        from agent.workspace import ensure_clone

        sid = "pr-tools-smoke-session-" + "a" * 33
        repo_dir = ensure_clone(sid)
        tools = {t.__name__: t for t in make_workspace_tools(repo_dir, sid)}

        # make a change, then open a PR
        tools["write_file"]("NEWFILE.md", "a change from the agent\n")
        out = tools["open_pr"]("Add NEWFILE", "adds a file")
        print("open_pr ->", out)
        assert "pull/123" in out, out
        assert pr_marker_path(sid).read_text().strip().endswith("/pull/123")

        # the branch must really exist on origin (proves push happened)
        ls = subprocess.run(
            ["git", "ls-remote", "--heads", str(remote)],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "refs/heads/trainer-agent/" in ls, ls
        print("branch pushed to origin: OK")

        out2 = tools["request_app_change"]("Need deck strategy", "please add strategy to state")
        print("request_app_change ->", out2)
        assert "issues/45" in out2, out2

    print("PASS")


if __name__ == "__main__":
    main()
