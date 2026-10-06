"""Loopback HTTP API. Static files are confined to the project's web directory."""

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .core import DeskError

MAX_BODY = 32768


def make_server(desk, web_dir, port=8765):
    web_root = Path(web_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "AXDesk/1.0"

        def _send(self, status, body, content_type="application/json; charset=utf-8", filename=None):
            if isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _error(self, error):
            self._send(error.status, {"error": str(error), "code": error.code})

        def _check_request(self, write=False):
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host", "").lower() not in allowed_hosts:
                raise DeskError("Loopback Host header required.", "forbidden_host", 403)
            if write:
                origin = self.headers.get("Origin")
                if origin and origin.lower() not in {f"http://{h}" for h in allowed_hosts}:
                    raise DeskError("Cross-origin writes are forbidden.", "forbidden_origin", 403)
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    raise DeskError("Cross-site writes are forbidden.", "forbidden_origin", 403)

        def do_GET(self):
            try:
                self._check_request()
                path = urlsplit(self.path).path
                if path == "/api/health":
                    self._send(200, {"status": "ok", "synthetic": True, "mode": "retrieval-only"})
                elif path == "/api/state":
                    self._send(200, desk.state())
                elif path == "/api/export":
                    self._send(200, desk.export(), "text/csv; charset=utf-8", "synthetic-energy-2026-09.csv")
                elif path.startswith("/api/"):
                    raise DeskError("API endpoint not found.", "not_found", 404)
                else:
                    decoded = unquote(path)
                    if "\x00" in decoded or "\\" in decoded or any(p in {"..", "."} for p in decoded.split("/")):
                        raise DeskError("Invalid static path.", "forbidden_path", 403)
                    target = (web_root / (decoded.lstrip("/") or "index.html")).resolve()
                    if not target.is_relative_to(web_root) or any(p.startswith(".") for p in target.relative_to(web_root).parts):
                        raise DeskError("Static path is outside the web directory.", "forbidden_path", 403)
                    if not target.is_file():
                        raise DeskError("File not found.", "not_found", 404)
                    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                    if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
                        content_type += "; charset=utf-8"
                    self._send(200, target.read_bytes(), content_type)
            except DeskError as error:
                self._error(error)

        def do_POST(self):
            try:
                self._check_request(write=True)
                if self.headers.get("Transfer-Encoding"):
                    raise DeskError("Chunked request bodies are unsupported.", "invalid_body", 400)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise DeskError("Invalid content length.", "invalid_body", 400)
                if length < 0 or length > MAX_BODY:
                    raise DeskError("Request body exceeds 32 KiB.", "body_too_large", 413)
                if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                    raise DeskError("JSON content type required.", "unsupported_media_type", 415)
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"), parse_float=str,
                                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                except (ValueError, UnicodeDecodeError):
                    raise DeskError("Invalid JSON body.", "invalid_json", 400)
                path = urlsplit(self.path).path
                if path == "/api/repair":
                    result = desk.repair(payload)
                elif path == "/api/review":
                    result = desk.review(payload)
                elif path == "/api/ask":
                    result = desk.ask(payload)
                elif path == "/api/reset":
                    if payload != {}:
                        raise DeskError("Reset accepts an empty JSON object.")
                    result = desk.reset()
                else:
                    raise DeskError("API endpoint not found.", "not_found", 404)
                self._send(200, result)
            except DeskError as error:
                self._error(error)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
