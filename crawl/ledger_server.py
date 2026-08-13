"""Localhost-only ledger API + UI shell (GET 只读；验证码人工解允许 POST)."""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import ledger_data as data  # noqa: E402
from crawl.captcha_flow import open_for_human, resolve_todo  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SHELL = ROOT / "data" / "web" / "ledger_app.html"
CAPTCHA_POST = {"/api/captcha/open", "/api/captcha/done"}


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict | list) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, code: int, body: bytes, content_type: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def route_api(path: str, qs: dict[str, list[str]]) -> tuple[int, dict]:
    def first(key: str, default: str | None = None) -> str | None:
        vals = qs.get(key)
        if not vals:
            return default
        return vals[0]

    if path == "/api/health":
        return 200, {
            "ok": True,
            "mode": "localhost_ledger",
            "bind": "127.0.0.1",
            "write_allow": sorted(CAPTCHA_POST),
        }
    if path == "/api/meta":
        return 200, data.meta()
    if path == "/api/summary":
        return 200, data.summary()
    if path == "/api/notices":
        return 200, data.notices(
            source_id=first("source_id") or None,
            province=first("province") or None,
            city=first("city") or None,
            clean_status=first("clean_status") or None,
            only_pass=_truthy(first("only_pass")),
            q=first("q") or None,
            limit=data.clamp_limit(first("limit"), 50),
            offset=data.clamp_offset(first("offset")),
        )
    if path == "/api/runs":
        return 200, data.runs(limit=data.clamp_limit(first("limit"), 40))
    if path == "/api/clean/stats":
        return 200, data.clean_stats()
    if path == "/api/keywords":
        return 200, data.keywords()
    if path == "/api/captcha":
        return 200, data.captcha(limit=data.clamp_limit(first("limit"), 40))
    if path == "/api/entities":
        return 200, data.entities(limit=data.clamp_limit(first("limit"), 100))
    return 404, {"ok": False, "error": "not_found", "path": path}


def route_captcha_post(path: str, body: dict) -> tuple[int, dict]:
    try:
        todo_id = int(body.get("id") or body.get("todo_id") or 0)
    except (TypeError, ValueError):
        todo_id = 0
    if todo_id <= 0:
        return 400, {"ok": False, "error": "bad_id"}
    if path == "/api/captcha/open":
        out = open_for_human(todo_id)
        return (200 if out.get("ok") else 400), out
    if path == "/api/captcha/done":
        out = resolve_todo(
            todo_id,
            cookie_header=body.get("cookie"),
            note=body.get("note"),
        )
        return (200 if out.get("ok") else 400), out
    return 404, {"ok": False, "error": "not_found", "path": path}


class LedgerHandler(BaseHTTPRequestHandler):
    server_version = "SpidermanLedger/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_HEAD(self) -> None:
        self._handle(write_body=False)

    def do_GET(self) -> None:
        self._handle(write_body=True)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        if path not in CAPTCHA_POST:
            _json_response(
                self,
                405,
                {"ok": False, "error": "readonly", "allow": ["GET", "HEAD"], "write_allow": sorted(CAPTCHA_POST)},
            )
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}
        try:
            code, payload = route_captcha_post(path, body)
        except Exception as e:  # noqa: BLE001
            code, payload = 500, {"ok": False, "error": "server_error", "detail": str(e)[:300]}
        _json_response(self, code, payload)

    def do_PUT(self) -> None:
        self._reject_write()

    def do_DELETE(self) -> None:
        self._reject_write()

    def do_PATCH(self) -> None:
        self._reject_write()

    def _reject_write(self) -> None:
        _json_response(
            self,
            405,
            {"ok": False, "error": "readonly", "allow": ["GET", "HEAD"], "write_allow": sorted(CAPTCHA_POST)},
        )

    def _handle(self, write_body: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        qs = parse_qs(parsed.query)

        if path in {"/", "/index.html", "/ledger", "/dashboard.html"}:
            if not SHELL.exists():
                _json_response(self, 500, {"ok": False, "error": "shell_missing", "path": str(SHELL)})
                return
            body = SHELL.read_bytes()
            if write_body:
                _text_response(self, 200, body, "text/html; charset=utf-8")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
            return

        if path.startswith("/api/"):
            try:
                code, payload = route_api(path, qs)
            except Exception as e:
                code, payload = 500, {"ok": False, "error": "server_error", "detail": str(e)[:300]}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if write_body:
                self.wfile.write(body)
            return

        _json_response(self, 404, {"ok": False, "error": "not_found", "path": path})


def make_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    host = host or os.environ.get("LEDGER_HOST", DEFAULT_HOST)
    # 0.0.0.0 仅用于 Docker/NAS 容器暴露；默认仍是 127.0.0.1
    allowed = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    if host not in allowed:
        raise ValueError(f"ledger bind host not allowed: {host} (use 127.0.0.1 or 0.0.0.0)")
    if port is None:
        port = int(os.environ.get("LEDGER_PORT", DEFAULT_PORT))
    else:
        port = int(port)
    return ThreadingHTTPServer((host, port), LedgerHandler)


def serve_forever(host: str | None = None, port: int | None = None) -> None:
    httpd = make_server(host, port)
    h, p = httpd.server_address[:2]
    print(f"LEDGER http://{h}:{p}/  (captcha POST allowed; Ctrl+C stop)", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
