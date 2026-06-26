"""Local test stub for the Trainer Agent front door.

A zero-dependency HTTP server that enforces the SAME request contract as the real
front door (``frontdoor/contract.py`` — shared, so it can't drift) but returns
CANNED replies instead of invoking the real agent. mtg-deck-shuffler runs this as
a test sidecar (``docker run``) to exercise its integration end to end — bearer
auth, request validation, the version header, and its own handling of
``reply``/``status``/``pr_url`` — entirely locally, with no AWS and no real agent.

The canned ``status`` is driven by the message text so the app can test each
branch of its UI:

  - "open the pr" / "pr please"  -> status "done"  + a fake ``pr_url``
  - "ask"                        -> status "asking"
  - "error" / "fail"             -> status "error"
  - otherwise                    -> status "chatting"

Run:   ``python3 stub.py``   (or via the published Docker image)
Env:   ``PORT`` (default 8080); ``STUB_BEARER`` — the token the app must present
       (default ``stub-token``).
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from contract import (
    INTERFACE_VERSION,
    INTERFACE_VERSION_HEADER,
    validate_request,
)

BEARER = os.environ.get("STUB_BEARER", "stub-token")
PORT = int(os.environ.get("PORT", "8080"))


def canned_reply(message):
    m = (message or "").lower()
    if "open the pr" in m or "pr please" in m:
        return {
            "reply": "[stub] opened a PR",
            "status": "done",
            "pr_url": "https://github.com/jessitron/mtg-deck-shuffler/pull/0",
        }
    if "ask" in m:
        return {"reply": "[stub] I have a question for you", "status": "asking"}
    if "error" in m or "fail" in m:
        return {"reply": "[stub] something went wrong", "status": "error"}
    return {"reply": "[stub] hi", "status": "chatting"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header(INTERFACE_VERSION_HEADER, INTERFACE_VERSION)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        result = validate_request(self.headers, raw, BEARER)
        if result[0] == "error":
            _, status, body = result
            return self._send(status, body)
        _, req = result
        self._send(200, canned_reply(req.get("message", "")))

    def do_GET(self):
        if self.path == "/ping":
            return self._send(200, {"status": "ok", "stub": True})
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # keep test output quiet
        pass


if __name__ == "__main__":
    print(f"front-door stub listening on :{PORT} (interface {INTERFACE_VERSION})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
