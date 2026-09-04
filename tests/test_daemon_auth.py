from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from clausula import Store
from clausula.adapters.mcp import McpProfile
from clausula.api.auth import (
    ConfirmationChallengeError,
    LocalAuthRegistry,
    LocalPrincipal,
)
from clausula.api.http import create_server


def _post(url: str, payload: dict, token: str, challenge: str | None = None) -> tuple[int, dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if challenge:
        headers["X-Clausula-Confirmation"] = challenge
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_challenge_expires_and_cannot_cross_principals() -> None:
    admin = LocalPrincipal("admin", McpProfile.ADMIN, "a" * 48)
    other = LocalPrincipal("other", McpProfile.ADMIN, "b" * 48)
    auth = LocalAuthRegistry((admin, other), challenge_ttl_seconds=10)
    arguments = {"institution": "broker", "name": "main"}

    challenge = auth.issue_challenge(
        admin, "account.create", arguments, now_monotonic=100
    )
    with pytest.raises(ConfirmationChallengeError, match="different principal"):
        auth.consume_challenge(
            challenge.nonce,
            other,
            "account.create",
            arguments,
            now_monotonic=101,
        )
    # A wrong-principal attempt does not transform the nonce into a valid nonce
    # for that other identity; the owner may still use the exact request once.
    auth.consume_challenge(
        challenge.nonce,
        admin,
        "account.create",
        arguments,
        now_monotonic=102,
    )
    with pytest.raises(ConfirmationChallengeError, match="already used"):
        auth.consume_challenge(
            challenge.nonce,
            admin,
            "account.create",
            arguments,
            now_monotonic=103,
        )

    expired = auth.issue_challenge(
        admin, "account.create", arguments, now_monotonic=200
    )
    with pytest.raises(ConfirmationChallengeError, match="expired"):
        auth.consume_challenge(
            expired.nonce,
            admin,
            "account.create",
            arguments,
            now_monotonic=211,
        )


def test_concurrent_http_writes_are_serialized_through_one_owner(tmp_path) -> None:
    store = Store(tmp_path / "home")
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    admin_token = server.clausula_auth.token_for("local-admin")
    requests = [
        {"institution": "broker", "name": f"account-{index}"}
        for index in range(12)
    ]
    try:
        challenges: list[str] = []
        for arguments in requests:
            status, body = _post(
                f"{base}/confirmations/challenge",
                {"capability": "account.create", "arguments": arguments},
                admin_token,
            )
            assert status == 200
            challenges.append(body["challenge"])

        def execute(item: tuple[dict, str]) -> tuple[int, dict]:
            arguments, challenge = item
            return _post(
                f"{base}/capabilities/account.create",
                arguments,
                admin_token,
                challenge,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(execute, zip(requests, challenges, strict=True)))
        assert [status for status, _ in results] == [200] * len(requests)
        assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == len(requests)
        assert store.verify_audit_chain()["valid"] is True

        invocations = store.db.execute(
            """SELECT count(*) FROM audit_events
               WHERE operation='http.invoke' AND actor_id='local-admin'
               AND json_extract(payload_json,'$.succeeded')=1"""
        ).fetchone()[0]
        assert invocations == len(requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
