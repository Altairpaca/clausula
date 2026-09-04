from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any, Iterable, Mapping

from clausula.adapters.mcp import McpProfile, PROFILE_PERMISSIONS


class AuthenticationError(PermissionError):
    pass


class ConfirmationChallengeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalPrincipal:
    principal_id: str
    profile: McpProfile
    token: str

    def __post_init__(self) -> None:
        if not self.principal_id.strip():
            raise ValueError("principal_id cannot be empty")
        if len(self.token) < 32:
            raise ValueError("local principal token is too short")

    @property
    def permissions(self) -> frozenset[str]:
        return PROFILE_PERMISSIONS[self.profile]


@dataclass(frozen=True, slots=True)
class ConfirmationChallenge:
    nonce: str
    principal_id: str
    capability: str
    request_sha256: str
    issued_at: float
    expires_at: float


class LocalAuthRegistry:
    """In-memory local identity and confirmation boundary for one daemon process.

    Tokens are generated at process start by default and are never persisted in
    canonical state. Permission sets are derived server-side from a fixed profile;
    callers cannot submit arbitrary permissions. Confirmation challenges are
    one-time, expire quickly, and bind principal + capability + canonical request.
    """

    def __init__(
        self,
        principals: Iterable[LocalPrincipal] = (),
        *,
        challenge_ttl_seconds: int = 120,
    ) -> None:
        if challenge_ttl_seconds <= 0:
            raise ValueError("challenge_ttl_seconds must be positive")
        self.challenge_ttl_seconds = int(challenge_ttl_seconds)
        self._principals: dict[str, LocalPrincipal] = {}
        self._tokens: dict[str, str] = {}
        self._challenges: dict[str, ConfirmationChallenge] = {}
        self._lock = threading.RLock()
        for principal in principals:
            self.add_principal(principal)

    @classmethod
    def ephemeral_default(cls) -> "LocalAuthRegistry":
        """Create non-persisted local read/advisor/admin identities for one run."""

        return cls(
            (
                LocalPrincipal(
                    "local-read",
                    McpProfile.PORTFOLIO_READ,
                    secrets.token_urlsafe(32),
                ),
                LocalPrincipal(
                    "local-advisor",
                    McpProfile.ADVISOR,
                    secrets.token_urlsafe(32),
                ),
                LocalPrincipal(
                    "local-admin",
                    McpProfile.ADMIN,
                    secrets.token_urlsafe(32),
                ),
            )
        )

    def add_principal(self, principal: LocalPrincipal) -> None:
        with self._lock:
            if principal.principal_id in self._principals:
                raise ValueError(f"duplicate principal_id: {principal.principal_id}")
            token_digest = self._token_digest(principal.token)
            if token_digest in self._tokens:
                raise ValueError("duplicate local principal token")
            self._principals[principal.principal_id] = principal
            self._tokens[token_digest] = principal.principal_id

    def principal(self, principal_id: str) -> LocalPrincipal:
        try:
            return self._principals[principal_id]
        except KeyError as exc:
            raise AuthenticationError("unknown local principal") from exc

    def token_for(self, principal_id: str) -> str:
        """Process-local bootstrap helper; never expose through an HTTP endpoint."""

        return self.principal(principal_id).token

    def credential_manifest(self) -> dict[str, Any]:
        """Return bootstrap credentials for a local 0600 runtime file only."""

        with self._lock:
            return {
                "format": "clausula-local-auth-v1",
                "principals": [
                    {
                        "principal_id": principal.principal_id,
                        "profile": principal.profile.value,
                        "token": principal.token,
                    }
                    for principal in sorted(
                        self._principals.values(), key=lambda item: item.principal_id
                    )
                ],
            }

    def authenticate_bearer(self, header: str | None) -> LocalPrincipal:
        if not header:
            raise AuthenticationError("Authorization bearer token is required")
        scheme, separator, value = header.partition(" ")
        if not separator or scheme.lower() != "bearer" or not value.strip():
            raise AuthenticationError("Authorization must use Bearer token")
        presented = self._token_digest(value.strip())
        with self._lock:
            matched_id = None
            for token_digest, principal_id in self._tokens.items():
                if hmac.compare_digest(token_digest, presented):
                    matched_id = principal_id
                    break
            if matched_id is None:
                raise AuthenticationError("invalid local bearer token")
            return self._principals[matched_id]

    def issue_challenge(
        self,
        principal: LocalPrincipal,
        capability: str,
        arguments: Mapping[str, Any],
        *,
        now_monotonic: float | None = None,
    ) -> ConfirmationChallenge:
        issued = time.monotonic() if now_monotonic is None else float(now_monotonic)
        nonce = secrets.token_urlsafe(32)
        challenge = ConfirmationChallenge(
            nonce=nonce,
            principal_id=principal.principal_id,
            capability=str(capability),
            request_sha256=self.request_digest(
                principal.principal_id, capability, arguments
            ),
            issued_at=issued,
            expires_at=issued + self.challenge_ttl_seconds,
        )
        with self._lock:
            self._purge_expired(issued)
            self._challenges[nonce] = challenge
        return challenge

    def consume_challenge(
        self,
        nonce: str | None,
        principal: LocalPrincipal,
        capability: str,
        arguments: Mapping[str, Any],
        *,
        now_monotonic: float | None = None,
    ) -> ConfirmationChallenge:
        if not nonce:
            raise ConfirmationChallengeError("a server-issued confirmation challenge is required")
        current = time.monotonic() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            self._purge_expired(current)
            challenge = self._challenges.get(nonce)
            if challenge is None:
                raise ConfirmationChallengeError("confirmation challenge is invalid, expired, or already used")
            if challenge.principal_id != principal.principal_id:
                raise ConfirmationChallengeError("confirmation challenge belongs to a different principal")
            if challenge.capability != capability:
                raise ConfirmationChallengeError("confirmation challenge is bound to a different capability")
            expected = self.request_digest(principal.principal_id, capability, arguments)
            if not hmac.compare_digest(challenge.request_sha256, expected):
                raise ConfirmationChallengeError("confirmation challenge is bound to different arguments")
            del self._challenges[nonce]
            return challenge

    @staticmethod
    def request_digest(
        principal_id: str, capability: str, arguments: Mapping[str, Any]
    ) -> str:
        canonical = json.dumps(
            {
                "principal_id": principal_id,
                "capability": capability,
                "arguments": dict(arguments),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _purge_expired(self, current: float) -> None:
        expired = [
            nonce
            for nonce, challenge in self._challenges.items()
            if challenge.expires_at < current
        ]
        for nonce in expired:
            self._challenges.pop(nonce, None)
