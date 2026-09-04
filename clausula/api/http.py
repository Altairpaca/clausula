from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from clausula.application import CoreRepository
from clausula.application.cockpit import CapitalCockpitService
from clausula.application.cockpit_plus import IntelligentCapitalCockpitService
from clausula.capabilities import (
    CapabilityError,
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)
from clausula.ui import workspace_document


HTML_CSP = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'"
)


def create_server(repository: CoreRepository) -> ThreadingHTTPServer:
    registry = build_core_registry(repository)
    cockpit = (
        IntelligentCapitalCockpitService(repository)
        if hasattr(repository, "db")
        else CapitalCockpitService(repository)
    )
    registry_lock = threading.RLock()

    class CapabilityHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/workspace"}:
                self._send_html(200, workspace_document())
                return
            if path == "/capabilities":
                with registry_lock:
                    payload = registry.describe()
                self._send(200, payload)
                return
            prefix = "/capabilities/"
            if path.startswith(prefix):
                name = unquote(path.removeprefix(prefix))
                try:
                    with registry_lock:
                        payload = registry.describe(name)
                    self._send(200, payload)
                except CapabilityError as error:
                    self._send_error(404, "unknown_capability", str(error))
                return
            self._send_error(404, "not_found", "resource not found")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/workspace/snapshot":
                try:
                    payload = self._read_json_object()
                    with registry_lock:
                        result = cockpit.snapshot(**payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    self._send_error(400, "invalid_snapshot_request", str(error))
                    return
                self._send(200, result)
                return

            prefix = "/capabilities/"
            if not path.startswith(prefix):
                self._send_error(404, "not_found", "resource not found")
                return
            try:
                payload = self._read_json_object()
                with registry_lock:
                    result = registry.execute(
                        unquote(path.removeprefix(prefix)),
                        payload,
                        permissions=self._permissions(),
                        confirmed=self.headers.get("X-Clausula-Confirmed") == "true",
                        dry_run=self.headers.get("X-Clausula-Dry-Run") == "true",
                    )
            except CapabilityPermissionError as error:
                self._send_error(403, "permission_denied", str(error))
                return
            except ConfirmationRequired as error:
                self._send_error(409, "confirmation_required", str(error))
                return
            except (CapabilityError, ValueError, json.JSONDecodeError) as error:
                self._send_error(400, "invalid_request", str(error))
                return
            self._send(200, result)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json_object(self) -> dict[str, Any]:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _permissions(self) -> tuple[str, ...]:
            return tuple(
                item.strip()
                for item in self.headers.get("X-Clausula-Permissions", "").split(",")
                if item.strip()
            )

        def _common_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, status: int, document: str) -> None:
            data = document.encode("utf-8")
            self.send_response(status)
            self._common_headers()
            self.send_header("Content-Security-Policy", HTML_CSP)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, status: int, code: str, message: str) -> None:
            self._send(status, {"error": code, "message": message})

    return ThreadingHTTPServer(("127.0.0.1", 0), CapabilityHandler)
