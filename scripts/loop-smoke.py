"""Bedrock-backed smoke for the real agent loop (JES-108).

Exercises agent.loop.run_turn end to end against a LOCAL fixture repo (no network
clone) but a REAL Bedrock model, so it proves: clone+instructions -> Strands Agent
-> model reply -> conversation persisted across turns. Needs AWS creds with
Bedrock access.

Run:
  AWS_PROFILE=sandbox AWS_REGION=us-west-2 \
    TRAINER_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0 \
    uv run --no-sync python scripts/loop-smoke.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

INSTRUCTIONS = """\
You help improve this app. For this smoke test specifically: when the user
greets you, reply with ONE short sentence confirming you can see the repo and
naming one file you find at the repo root. Do not modify any files.
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def main():
    if not os.environ.get("TRAINER_MODEL_ID"):
        os.environ["TRAINER_MODEL_ID"] = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["TRAINER_WORKSPACE_ROOT"] = str(tmp / "sessions")

        repo = tmp / "fixture-repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "trainer-agent").mkdir()
        (repo / "trainer-agent" / "instructions.md").write_text(INSTRUCTIONS)
        (repo / "README.md").write_text("# Fixture App\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fixture")
        os.environ["TRAINER_REPO_URL"] = str(repo)

        from agent.loop import _session_storage_dir, run_turn

        sid = "loop-smoke-session-aaaaaaaaaaaaaaaaaaaaaaaa"

        print("== turn 1 ==")
        r1 = run_turn({"message": "Hello! Can you see the repo?"}, sid)
        print("status:", r1["status"])
        print("reply :", r1["reply"][:300])
        assert r1["status"] == "chatting", f"expected chatting, got {r1}"
        assert r1["reply"].strip(), "empty reply"

        print("== turn 2 (same session -> conversation should persist) ==")
        r2 = run_turn({"message": "What did I just ask you?"}, sid)
        print("status:", r2["status"])
        print("reply :", r2["reply"][:300])
        assert r2["status"] == "chatting"

        storage = Path(_session_storage_dir(sid))
        assert storage.exists(), "session storage dir should exist"
        files = list(storage.rglob("*.json"))
        assert files, "conversation should be persisted to disk"
        print(f"persisted {len(files)} session json files under {storage.name}/")

    print("PASS")


if __name__ == "__main__":
    main()
