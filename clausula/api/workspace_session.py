from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from http.cookies import SimpleCookie
import secrets
import threading
import time
from typing import Callable, Iterable


WORKSPACE_SESSION_COOKIE = "clausula_workspace_session"
DEFAULT_BOOTSTRAP_TTL_SECONDS = 120
DEFAULT_SESSION_TTL_SECONDS = 1800


class WorkspaceSessionError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceSession:
    session_id: str
    scopes: frozenset[str]
    issued_at: float
    expires_at: float


class WorkspaceSessionRegistry:
    """Process-local, non-capability browser session boundary.

    One daemon bootstrap secret can be exchanged exactly once for an HttpOnly
    session cookie.  The resulting session carries only explicit workflow scopes;
    it is not a LocalPrincipal and cannot be used as `/capabilities/*` authority.
    """

    def __init__(
        self,
        *,
        scopes: Iterable[str] = (),
        bootstrap_ttl_seconds: int = DEFAULT_BOOTSTRAP_TTL_SECONDS,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if bootstrap_ttl_seconds <= 0 or session_ttl_seconds <= 0:
            raise ValueError("workspace session TTLs must be positive")
        normalized_scopes = frozenset(
            str(scope).strip() for scope in scopes if str(scope).strip()
        )
        self.scopes = normalized_scopes
        self.bootstrap_ttl_seconds = int(bootstrap_ttl_seconds)
        self.session_ttl_seconds = int(session_ttl_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        bootstrap = secrets.token_urlsafe(32)
        issued = float(clock())
        self._bootstrap_token = bootstrap
        self._bootstrap_digest = self._digest(bootstrap)
        self._bootstrap_issued_at = issued
        self._bootstrap_expires_at = issued + self.bootstrap_ttl_seconds
        self._bootstrap_consumed = False
        self._sessions: dict[str, WorkspaceSession] = {}

    @property
    def bootstrap_token(self) -> str:
        """Server/daemon-only token used solely in the browser URL fragment."""

        return self._bootstrap_token

    def exchange(
        self, bootstrap_token: str, *, now_monotonic: float | None = None
    ) -> WorkspaceSession:
        current = self._now(now_monotonic)
        presented = self._digest(str(bootstrap_token))
        with self._lock:
            self._purge_expired(current)
            if self._bootstrap_consumed:
                raise WorkspaceSessionError("workspace bootstrap is invalid or already used")
            if current > self._bootstrap_expires_at:
                raise WorkspaceSessionError("workspace bootstrap has expired")
            if not hmac.compare_digest(presented, self._bootstrap_digest):
                raise WorkspaceSessionError("workspace bootstrap is invalid")
            self._bootstrap_consumed = True
            session_id = secrets.token_urlsafe(32)
            session = WorkspaceSession(
                session_id=session_id,
                scopes=self.scopes,
                issued_at=current,
                expires_at=current + self.session_ttl_seconds,
            )
            self._sessions[self._digest(session_id)] = session
            return session

    def authenticate_cookie(
        self,
        cookie_header: str | None,
        *,
        required_scope: str | None = None,
        now_monotonic: float | None = None,
    ) -> WorkspaceSession:
        current = self._now(now_monotonic)
        if not cookie_header:
            raise WorkspaceSessionError("workspace session cookie is required")
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception as exc:
            raise WorkspaceSessionError("workspace session cookie is invalid") from exc
        morsel = cookie.get(WORKSPACE_SESSION_COOKIE)
        if morsel is None or not morsel.value:
            raise WorkspaceSessionError("workspace session cookie is required")
        presented = self._digest(morsel.value)
        with self._lock:
            self._purge_expired(current)
            matched: WorkspaceSession | None = None
            for digest, session in self._sessions.items():
                if hmac.compare_digest(digest, presented):
                    matched = session
                    break
            if matched is None:
                raise WorkspaceSessionError("workspace session is invalid or expired")
            if required_scope is not None and required_scope not in matched.scopes:
                raise WorkspaceSessionError(
                    f"workspace session lacks required scope: {required_scope}"
                )
            return matched

    def cookie_header(self, session: WorkspaceSession) -> str:
        max_age = max(1, int(session.expires_at - session.issued_at))
        return (
            f"{WORKSPACE_SESSION_COOKIE}={session.session_id}; "
            f"Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict"
        )

    def session_count(self, *, now_monotonic: float | None = None) -> int:
        current = self._now(now_monotonic)
        with self._lock:
            self._purge_expired(current)
            return len(self._sessions)

    def _now(self, supplied: float | None) -> float:
        return float(self._clock()) if supplied is None else float(supplied)

    def _purge_expired(self, current: float) -> None:
        expired = [
            digest
            for digest, session in self._sessions.items()
            if session.expires_at < current
        ]
        for digest in expired:
            self._sessions.pop(digest, None)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_BOOTSTRAP_TTL_SECONDS",
    "DEFAULT_SESSION_TTL_SECONDS",
    "WORKSPACE_SESSION_COOKIE",
    "WorkspaceSession",
    "WorkspaceSessionError",
    "WorkspaceSessionRegistry",
]
