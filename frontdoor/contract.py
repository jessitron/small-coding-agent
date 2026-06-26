"""Shared front-door request contract — the single source of truth for what a
valid request looks like.

Imported by BOTH the real Lambda handler (``frontdoor/handler.py``) and the local
test stub (``frontdoor/stub.py``). Keeping validation here is the whole point: the
stub enforces *exactly* what production enforces, so a green test against the stub
means something. If the rules lived in two places they would drift and the stub
would start lying.

Pure stdlib — no AWS, no OpenTelemetry — so it can be imported by the real Lambda
handler unchanged. (The stub itself is no longer zero-dependency: it adds OTel to
emit its own spans — see ``frontdoor/stub.py``. This module stays stdlib-only.)

Versioned with ``INTERFACE.md`` (the canonical spec the app integrates against).
Bump both together; see that doc's Versioning section.
"""

import hmac
import json

INTERFACE_VERSION = "2.1"
INTERFACE_VERSION_HEADER = "X-Trainer-Agent-Interface-Version"

# AgentCore requires runtimeSessionId >= 33 chars.
MIN_SESSION_ID_LEN = 33


def header_lookup(headers, name):
    """Case-insensitive header lookup over anything with ``.items()`` (a dict or
    an ``http.client.HTTPMessage``). Returns the value or ``None``."""
    name = name.lower()
    for k, v in headers.items():
        if k.lower() == name:
            return v
    return None


def bearer_ok(headers, expected_bearer):
    """True iff the ``Authorization`` header carries the expected bearer token.
    Constant-time compare so a wrong token can't be guessed via timing."""
    auth = header_lookup(headers, "authorization") or ""
    presented = auth[7:] if auth.lower().startswith("bearer ") else ""
    return bool(presented) and hmac.compare_digest(presented, expected_bearer)


def validate_request(headers, raw_body, expected_bearer):
    """Validate an incoming front-door request.

    ``raw_body`` may be ``bytes``, ``str``, or ``None``. Returns one of:

      ``("ok", body)``                        — valid; ``body`` is the parsed dict
      ``("error", status_code, error_body)``  — reject with this status + JSON body

    On success the whole parsed ``body`` is returned (``message``, ``session_id``,
    and the v2.0 ``seq`` / ``state``), so the caller forwards the v2.0 fields
    without the contract needing to know what they mean. The *validation decision*
    still lives here so the stub and the real handler agree by construction.
    """
    if not bearer_ok(headers, expected_bearer):
        return ("error", 401, {"error": "unauthorized"})
    try:
        body = json.loads(raw_body or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        return ("error", 400, {"error": "invalid JSON body"})
    if not isinstance(body, dict):
        return ("error", 400, {"error": "invalid JSON body"})
    session_id = body.get("session_id")
    if not session_id or len(session_id) < MIN_SESSION_ID_LEN:
        return ("error", 400, {"error": "session_id required (>= 33 chars)"})
    return ("ok", body)
