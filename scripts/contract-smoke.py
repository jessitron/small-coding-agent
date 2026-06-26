"""Offline smoke for the v2.0 wire contract + the seq context-loss check (JES-109).

No AWS, no Bedrock. Covers:
- frontdoor/contract.py: version is 2.0; success returns the parsed body with
  seq/state preserved; the 401/400 rejections still hold.
- agent.loop seq check: a seq that doesn't match the session's turn count returns
  an honest status:error (context lost); a matching seq passes the gate and
  proceeds to the workspace step.

Run:  uv run --no-sync python scripts/contract-smoke.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "frontdoor"))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

SID = "seq-smoke-session-" + "a" * 33


def test_contract():
    from contract import INTERFACE_VERSION, validate_request

    assert INTERFACE_VERSION == "2.0", INTERFACE_VERSION
    hdrs = {"Authorization": "Bearer t"}

    body = json.dumps(
        {"message": "hi", "session_id": "x" * 33, "seq": 3, "state": {"deck": "boros"}}
    )
    tag, parsed = validate_request(hdrs, body, "t")
    assert tag == "ok", parsed
    assert parsed["seq"] == 3 and parsed["state"] == {"deck": "boros"}, parsed
    assert parsed["message"] == "hi"

    assert validate_request({}, "{}", "t")[1] == 401  # no/!bearer
    assert validate_request(hdrs, "{not json", "t")[1] == 400  # bad json
    assert validate_request(hdrs, json.dumps({"session_id": "short"}), "t")[1] == 400
    print("contract (v2.0, seq/state passthrough, rejections): OK")


def _make_bare_repo(path: Path):
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("no trainer-agent dir here\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=path, check=True)


def test_seq():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["TRAINER_WORKSPACE_ROOT"] = str(tmp / "sessions")
        from agent.loop import run_turn

        # Fresh session (turns_seen=0); client claims this is message #5 -> lost.
        r = run_turn({"message": "hi", "seq": 5}, SID)
        assert r["status"] == "error" and "lost the context" in r["reply"], r
        print("seq mismatch on fresh session -> context-loss error: OK")

        # seq=1 matches a fresh session: passes the gate, reaches the workspace
        # step, and fails there (bare repo has no instructions) -> proves the gate
        # let it through without needing Bedrock.
        bare = tmp / "bare"
        _make_bare_repo(bare)
        os.environ["TRAINER_REPO_URL"] = str(bare)
        r2 = run_turn({"message": "hi", "seq": 1}, SID)
        assert r2["status"] == "error" and "instructions.md" in r2["reply"], r2
        print("seq=1 passes the gate, reaches workspace (missing brief): OK")


def main():
    test_contract()
    test_seq()
    print("PASS")


if __name__ == "__main__":
    main()
