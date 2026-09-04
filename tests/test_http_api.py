from __future__ import annotations

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from clausula import Store
from clausula.api.http import create_server


def _request(url: str, method: str = "GET", payload: dict | None = None, permissions: tuple[str, ...] = (), confirmed: bool = False, dry_run: bool = False) -> tuple[int, dict | list]:
    headers = {
        "Accept": "application/json",
        "X-Clausula-Permissions": ",".join(permissions),
        "X-Clausula-Confirmed": str(confirmed).lower(),
        "X-Clausula-Dry-Run": str(dry_run).lower(),
    }
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


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


def test_http_projects_registry_and_enforces_write_contract(tmp_path) -> None:
    server = create_server(Store(tmp_path / "home"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, capabilities = _request(f"{base}/capabilities")
        assert status == 200
        assert any(item["name"] == "research.search" for item in capabilities)

        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            {"institution": "broker", "name": "main"},
        )
        assert status == 403
        assert body["error"] == "permission_denied"

        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            {"institution": "broker", "name": "main"},
            permissions=("ledger:write",),
        )
        assert status == 409
        assert body["error"] == "confirmation_required"

        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            {"institution": "broker", "name": "main"},
            permissions=("ledger:write",),
            dry_run=True,
        )
        assert status == 200
        assert body["would_execute"] is True

        status, body = _request(
            f"{base}/capabilities/account.create",
            "POST",
            {"institution": "broker", "name": "main"},
            permissions=("ledger:write",),
            confirmed=True,
        )
        assert status == 200
        assert body["account_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
