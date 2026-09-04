from __future__ import annotations

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from clausula import Store
from clausula.api.http import create_server
from clausula.application import PortfolioService


def _request(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    *,
    token: str | None = None,
    challenge: str | None = None,
    spoof_permissions: tuple[str, ...] = (),
    spoof_confirmed: bool = False,
    dry_run: bool = False,
) -> tuple[int, dict | list]:
    headers = {
        "Accept": "application/json",
        "X-Clausula-Permissions": ",".join(spoof_permissions),
        "X-Clausula-Confirmed": str(spoof_confirmed).lower(),
        "X-Clausula-Dry-Run": str(dry_run).lower(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if challenge:
        headers["X-Clausula-Confirmation"] = challenge
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _challenge(base: str, token: str, capability: str, arguments: dict) -> str:
    status, body = _request(
        f"{base}/confirmations/challenge",
        "POST",
        {"capability": capability, "arguments": arguments},
        token=token,
    )
    assert status == 200
    assert isinstance(body, dict)
    return str(body["challenge"])


def test_http_serves_read_only_capital_cockpit_with_security_headers(tmp_path) -> None:
    server = create_server(Store(tmp_path / "home"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base}/") as response:
            document = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
            assert "Capital Cockpit" in document
            assert "LOCAL · READ ONLY" in document
            assert "Known as of" in document
            assert "recommendation.transition" not in document
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_workspace_snapshot_remains_anonymous_but_read_only(tmp_path) -> None:
    store = Store(tmp_path / "home")
    portfolio_id = PortfolioService(store).create("Household", "USD")
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = _request(
            f"{base}/workspace/snapshot",
            "POST",
            {
                "portfolio_id": portfolio_id,
                "as_of": "2026-09-04",
                "known_as_of": "2026-09-04",
            },
        )
        assert status == 200
        assert isinstance(body, dict)
        assert body["format"] == "clausula-capital-cockpit-v1"
        assert body["portfolio"]["id"] == portfolio_id
        assert body["valuation"]["complete"] is True
        assert body["valuation"]["total_value"] == "0"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_client_headers_cannot_self_grant_permissions_or_confirmation(tmp_path) -> None:
    store = Store(tmp_path / "home")
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    arguments = {"institution": "broker", "name": "main"}
    try:
        status, capabilities = _request(f"{base}/capabilities")
        assert status == 200
        assert any(item["name"] == "research.search" for item in capabilities)

        # The legacy self-declared permission/confirmation headers are ignored.
        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            arguments,
            spoof_permissions=("ledger:write",),
            spoof_confirmed=True,
        )
        assert status == 401
        assert body["error"] == "authentication_required"

        read_token = server.clausula_auth.token_for("local-read")
        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            arguments,
            token=read_token,
            spoof_permissions=("ledger:write",),
            spoof_confirmed=True,
        )
        assert status == 403
        assert body["error"] == "permission_denied"

        admin_token = server.clausula_auth.token_for("local-admin")
        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            arguments,
            token=admin_token,
            spoof_confirmed=True,
        )
        assert status == 409
        assert body["error"] == "confirmation_required"

        # Dry-run is permission checked but deliberately does not need a challenge.
        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            arguments,
            token=admin_token,
            dry_run=True,
        )
        assert status == 200
        assert body["would_execute"] is True
        assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_confirmation_is_bound_to_exact_request_and_single_use(tmp_path) -> None:
    store = Store(tmp_path / "home")
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    admin_token = server.clausula_auth.token_for("local-admin")
    arguments = {"institution": "broker", "name": "main"}
    try:
        nonce = _challenge(base, admin_token, "account.create", arguments)

        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            {"institution": "broker", "name": "tampered"},
            token=admin_token,
            challenge=nonce,
        )
        assert status == 409
        assert body["error"] == "confirmation_required"
        assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0

        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            arguments,
            token=admin_token,
            challenge=nonce,
        )
        assert status == 200
        assert body["account_id"]
        assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1

        # Replaying the exact nonce cannot execute the request twice.
        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            arguments,
            token=admin_token,
            challenge=nonce,
        )
        assert status == 409
        assert body["error"] == "confirmation_required"
        assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1

        invocation = store.db.execute(
            """SELECT actor_type,actor_id,payload_json FROM audit_events
               WHERE operation='http.invoke' AND object_type='capability_invocation'
               AND json_extract(payload_json,'$.succeeded')=1
               ORDER BY sequence DESC LIMIT 1"""
        ).fetchone()
        assert invocation is not None
        assert invocation["actor_type"] == "principal"
        assert invocation["actor_id"] == "local-admin"
        payload = json.loads(invocation["payload_json"])
        assert payload["capability"] == "account.create"
        assert payload["confirmed"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
