"""Lightweight HTTP control plane — accepts operator instructions via curl."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger(__name__)

# Thread-safe store for operator instructions + recent activity
_lock = threading.Lock()
_state = {
    "instructions": [],       # list of {"text": ..., "ts": ...}
    "last_cycle": None,       # summary of last trading cycle
    "started_at": time.time(),
}

MAX_INSTRUCTIONS = 20


# ── Public API for other modules ─────────────────────────────

def get_instructions() -> list[str]:
    """Return current operator instructions as a list of strings."""
    with _lock:
        return [i["text"] for i in _state["instructions"]]


def set_last_cycle(summary: dict):
    """Record what happened in the last trading cycle."""
    with _lock:
        _state["last_cycle"] = summary


# ── HTTP handler ─────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _send_json(self, code: int, obj: dict):
        body = json.dumps(obj, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})

        elif self.path == "/status":
            with _lock:
                self._send_json(200, {
                    "instructions": _state["instructions"],
                    "last_cycle": _state["last_cycle"],
                    "uptime_s": int(time.time() - _state["started_at"]),
                })

        elif self.path == "/instructions":
            with _lock:
                self._send_json(200, {"instructions": _state["instructions"]})

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/instruct":
            raw = self._read_body()
            # Accept plain text or JSON {"text": "..."}
            try:
                data = json.loads(raw)
                text = data.get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                text = raw.decode("utf-8", errors="replace").strip()

            if not text:
                self._send_json(400, {"error": "empty instruction"})
                return

            with _lock:
                _state["instructions"].append({"text": text, "ts": time.time()})
                # Keep only the most recent instructions
                if len(_state["instructions"]) > MAX_INSTRUCTIONS:
                    _state["instructions"] = _state["instructions"][-MAX_INSTRUCTIONS:]
                current = list(_state["instructions"])

            log.info("Operator instruction added: %s", text[:100])
            self._send_json(200, {"ok": True, "instructions": current})

        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path == "/instruct":
            with _lock:
                _state["instructions"].clear()
            log.info("Operator instructions cleared")
            self._send_json(200, {"ok": True, "instructions": []})
        else:
            self._send_json(404, {"error": "not found"})


def start(port: int | None = None):
    """Start the control server in a daemon thread."""
    port = port or int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Control server listening on :%d", port)
