from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from clausula.adapters.equity_case import EquityCaseProjection
from clausula.adapters.execution import ExecutionRepositoryProjection
from clausula.adapters.workspace import DecisionWorkspaceProjection
from clausula.application import CoreRepository, DecisionWorkspaceService
from clausula.application.cockpit import CapitalCockpitService
from clausula.application.equity_monitor import EquityCaseService
from clausula.capabilities import (
    CapabilityError,
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)
from clausula.ui import workspace_document

from .auth import (
    AuthenticationError,
    ConfirmationChallengeError,
    LocalAuthRegistry,
    LocalPrincipal,
)


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


def create_server(
    repository: CoreRepository,
    *,
    auth: LocalAuthRegistry | None = None,
) -> ThreadingHTTPServer:
    """Create the loopback projection with one process-local auth/write owner."""

    registry = build_core_registry(repository)
    auth_registry = auth or LocalAuthRegistry.ephemeral_default()
    execution_repository = (
        ExecutionRepositoryProjection(repository) if hasattr(repository, "db") else None
    )
    decision_workspace = (
        DecisionWorkspaceService(DecisionWorkspaceProjection(repository))
        if hasattr(repository, "db")
        else None
    )
    equity_monitor = (
        EquityCaseService(EquityCaseProjection(repository))
        if hasattr(repository, "db")
        else None
    )
    cockpit = CapitalCockpitService(
        repository, execution_repository=execution_repository
    )
    # This lock is the daemon's single in-process capability owner. A later Unix
    # socket/process-lock layer can prevent a second OS process from opening the
    # same writable database; callers of this server cannot bypass this owner.
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
                self._workspace_snapshot()
                return
            if path == "/confirmations/challenge":
                self._issue_confirmation_challenge()
                return
            prefix = "/capabilities/"
            if path.startswith(prefix):
                self._invoke_capability(unquote(path.removeprefix(prefix)))
                return
            self._send_error(404, "not_found", "resource not found")

        def _workspace_snapshot(self) -> None:
            # Intentionally anonymous and read-only. This route bypasses the
            # capability write surface and exposes only deterministic projections.
            try:
                payload = self._read_json_object()
                with registry_lock:
                    result = cockpit.snapshot(**payload)
                    if decision_workspace is not None:
                        result["decision_workspace"] = decision_workspace.snapshot(
                            payload["portfolio_id"],
                            payload["as_of"],
                            known_as_of=payload.get("known_as_of"),
                        )
                    else:
                        result["decision_workspace"] = {
                            "status": "unavailable",
                            "reason": "decision workspace requires the local SQLite projection",
                        }
                    if equity_monitor is not None:
                        result["equity_monitor"] = equity_monitor.portfolio_snapshot(
                            payload["portfolio_id"],
                            payload["as_of"],
                            known_as_of=payload.get("known_as_of"),
                        )
                    else:
                        result["equity_monitor"] = {
                            "status": "unavailable",
                            "reason": "equity monitor requires the local SQLite projection",
                        }
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_error(400, "invalid_snapshot_request", str(error))
                return
            self._send(200, result)

        def _issue_confirmation_challenge(self) -> None:
            try:
                principal = self._principal()
                request = self._read_json_object()
                capability = str(request.get("capability") or "").strip()
                arguments = request.get("arguments")
                if not capability or not isinstance(arguments, dict):
                    raise ValueError("capability and object arguments are required")
                with registry_lock:
                    spec = registry.get(capability)
                    # A dry-run validates both permission and input schema without
                    # executing any side effect or bypassing the future challenge.
                    registry.execute(
                        capability,
                        arguments,
                        permissions=principal.permissions,
                        dry_run=True,
                    )
                if not spec.confirmation_required:
                    raise ValueError("capability does not require confirmation")
                challenge = auth_registry.issue_challenge(
                    principal, capability, arguments
                )
            except AuthenticationError as error:
                self._send_error(401, "authentication_required", str(error))
                return
            except CapabilityPermissionError as error:
                self._send_error(403, "permission_denied", str(error))
                return
            except (CapabilityError, ValueError, json.JSONDecodeError) as error:
                self._send_error(400, "invalid_confirmation_request", str(error))
                return
            self._send(
                200,
                {
                    "challenge": challenge.nonce,
                    "capability": challenge.capability,
                    "principal_id": challenge.principal_id,
                    "request_sha256": challenge.request_sha256,
                    "expires_in_seconds": auth_registry.challenge_ttl_seconds,
                },
            )

        def _invoke_capability(self, name: str) -> None:
            principal: LocalPrincipal | None = None
            spec = None
            dry_run = self.headers.get("X-Clausula-Dry-Run") == "true"
            try:
                principal = self._principal()
                payload = self._read_json_object()
                with registry_lock:
                    spec = registry.get(name)
                    confirmed = False
                    if spec.confirmation_required and not dry_run:
                        auth_registry.consume_challenge(
                            self.headers.get("X-Clausula-Confirmation"),
                            principal,
                            name,
                            payload,
                        )
                        confirmed = True
                    result = registry.execute(
                        name,
                        payload,
                        permissions=principal.permissions,
                        confirmed=confirmed,
                        dry_run=dry_run,
                    )
                self._record_invocation(principal, name, spec.side_effect.value, confirmed, True)
            except AuthenticationError as error:
                self._send_error(401, "authentication_required", str(error))
                return
            except CapabilityPermissionError as error:
                if principal is not None and spec is not None:
                    self._record_invocation(
                        principal, name, spec.side_effect.value, False, False
                    )
                self._send_error(403, "permission_denied", str(error))
                return
            except ConfirmationChallengeError as error:
                if principal is not None and spec is not None:
                    self._record_invocation(
                        principal, name, spec.side_effect.value, False, False
                    )
                self._send_error(409, "confirmation_required", str(error))
                return
            except ConfirmationRequired as error:
                if principal is not None and spec is not None:
                    self._record_invocation(
                        principal, name, spec.side_effect.value, False, False
                    )
                self._send_error(409, "confirmation_required", str(error))
                return
            except (CapabilityError, ValueError, json.JSONDecodeError) as error:
                if principal is not None and spec is not None:
                    self._record_invocation(
                        principal, name, spec.side_effect.value, False, False
                    )
                self._send_error(400, "invalid_request", str(error))
                return
            self._send(200, result)

        def _record_invocation(
            self,
            principal: LocalPrincipal,
            capability: str,
            side_effect: str,
            confirmed: bool,
            succeeded: bool,
        ) -> None:
            recorder = getattr(repository, "record_adapter_invocation", None)
            if recorder is None:
                return
            with registry_lock:
                recorder(
                    adapter="http",
                    actor_type="principal",
                    actor_id=principal.principal_id,
                    capability=capability,
                    side_effect=side_effect,
                    confirmed=confirmed,
                    succeeded=succeeded,
                )

        def _principal(self) -> LocalPrincipal:
            return auth_registry.authenticate_bearer(
                self.headers.get("Authorization")
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json_object(self) -> dict[str, Any]:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

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

    server = ThreadingHTTPServer(("127.0.0.1", 0), CapabilityHandler)
    # Process-local bootstrap access for CLI/workspace launchers and tests. There
    # is deliberately no HTTP endpoint that returns these bearer tokens.
    server.clausula_auth = auth_registry  # type: ignore[attr-defined]
    return server
