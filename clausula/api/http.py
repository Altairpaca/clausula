from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from clausula.capabilities import (
    CapabilityError,
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)
from clausula.application import CoreRepository


def create_server(repository: CoreRepository) -> ThreadingHTTPServer:
    registry = build_core_registry(repository)
    registry_lock = threading.RLock()

    class CapabilityHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
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
            prefix = "/capabilities/"
            path = urlparse(self.path).path
            if not path.startswith(prefix):
                self._send_error(404, "not_found", "resource not found")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
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

        def _permissions(self) -> tuple[str, ...]:
            return tuple(
                item.strip()
                for item in self.headers.get("X-Clausula-Permissions", "").split(",")
                if item.strip()
            )

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, status: int, code: str, message: str) -> None:
            self._send(status, {"error": code, "message": message})

    return ThreadingHTTPServer(("127.0.0.1", 0), CapabilityHandler)
