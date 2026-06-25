"""GitHub authentication for the Trainer Agent runtime.

The agent clones, pushes, opens PRs (``open_pr``), and files issues
(``request_app_change``) on ``jessitron/mtg-deck-shuffler``. All of that needs a
GitHub credential. Per ``design/architecture.md`` it's a **fine-grained PAT**,
kept in **AWS Secrets Manager** (``trainer-agent/github-pat``) and fetched at
runtime — never baked into the image.

Two sources, in priority order:

1. **Env var ``GITHUB_TOKEN``** — the local path. ``main.py`` loads a gitignored
   ``.env`` before anything else, so locally you just set it there.
2. **Secrets Manager** — the prod path. No env var in the AgentCore image, so we
   fetch the secret with the runtime's execution role (which has
   ``secretsmanager:GetSecretValue`` on this secret; see
   ``scripts/aws/permissions-policy.json``).

The token is treated as secret throughout: it is never logged, never written to
disk, and never set as a span attribute. ``configure_git_credentials`` wires
``git`` to read it from the process environment via a credential helper, so it
stays in memory only. ``gh`` picks up ``GH_TOKEN`` from the same environment.
"""

import os
import subprocess

SECRET_ID = "trainer-agent/github-pat"
REGION = "us-west-2"


def get_github_token():
    """Return the GitHub PAT, preferring the local env var, falling back to
    Secrets Manager. Raises ``RuntimeError`` if neither is available so the
    failure is loud (the agent can turn it into an honest ``status: error``)."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    # Prod path: fetch from Secrets Manager. Import boto3 lazily so local runs
    # with GITHUB_TOKEN set don't pay the import.
    import boto3

    try:
        client = boto3.client("secretsmanager", region_name=REGION)
        resp = client.get_secret_value(SecretId=SECRET_ID)
    except Exception as exc:  # don't leak anything but the failure itself
        raise RuntimeError(
            f"could not read GitHub PAT from Secrets Manager ({SECRET_ID})"
        ) from exc
    return resp["SecretString"]


def configure_git_credentials(token=None):
    """Make ``git`` and ``gh`` authenticate as the PAT, non-interactively, without
    writing the token to disk.

    - Puts the token in ``GITHUB_TOKEN`` and ``GH_TOKEN`` in this process's
      environment (``gh`` reads ``GH_TOKEN`` automatically).
    - Installs a global ``git`` credential helper that echoes the token *from the
      environment* for ``github.com`` HTTPS — so the secret lives only in memory,
      never in ``~/.gitconfig`` or a credential store.

    Idempotent: safe to call on every invoke. Returns nothing; raises if the
    token can't be obtained.
    """
    token = token or get_github_token()
    os.environ["GITHUB_TOKEN"] = token
    os.environ["GH_TOKEN"] = token

    # Credential helper reads the password from $GITHUB_TOKEN at call time; the
    # token value itself is NOT stored in git config.
    helper = (
        '!f() { echo "username=x-access-token"; '
        'echo "password=$GITHUB_TOKEN"; }; f'
    )
    subprocess.run(
        ["git", "config", "--global", "credential.https://github.com.helper", helper],
        check=True,
    )
