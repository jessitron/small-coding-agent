"""Smoke test for GitHub auth (JES-106).

Proves the agent can obtain its GitHub PAT and wire git to use it, WITHOUT ever
printing the token. By default it exercises the **prod path** (Secrets Manager):
it ignores any local GITHUB_TOKEN so a green run means the secret + the runtime's
read permission are actually working.

Run (needs AWS creds for the sandbox account):

    AWS_PROFILE=sandbox uv run --no-sync python scripts/github-auth-smoke.py

Pass --allow-env to instead honor a local GITHUB_TOKEN (the .env path).
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def main():
    if "--allow-env" not in sys.argv:
        # Force the Secrets Manager branch so this really tests prod auth.
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GH_TOKEN", None)

    from agent.github_auth import configure_git_credentials, get_github_token

    token = get_github_token()
    assert token, "no token returned"
    print(
        f"token obtained: length={len(token)} "
        f"fine_grained={token.startswith('github_pat_')}"
    )

    configure_git_credentials(token)
    # The helper must reference the env var, NOT embed the token value.
    helper = subprocess.run(
        ["git", "config", "--global", "credential.https://github.com.helper"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert "$GITHUB_TOKEN" in helper, "helper should read token from env"
    assert token not in helper, "token value must NOT be written into git config"
    print("git credential helper installed (reads token from env, value not on disk)")
    print("PASS")


if __name__ == "__main__":
    main()
