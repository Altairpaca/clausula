from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from clausula import LedgerService, Store
from clausula.adapters.mcp import McpProfile
from clausula.api.auth import LocalAuthRegistry
from clausula.api.daemon import DaemonAlreadyRunning, DaemonLease, write_auth_manifest


def test_daemon_lease_rejects_second_owner(tmp_path: Path) -> None:
    path = tmp_path / "home" / "daemon.lock"
    first = DaemonLease(path).acquire()
    try:
        with pytest.raises(DaemonAlreadyRunning):
            DaemonLease(path).acquire()
    finally:
        first.release()
    assert not path.exists()


def test_auth_manifest_is_private_ephemeral_bootstrap(tmp_path: Path) -> None:
    auth = LocalAuthRegistry.ephemeral_default()
    path = write_auth_manifest(
        tmp_path / "home" / "daemon-auth.json",
        auth,
        base_url="http://127.0.0.1:43123",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == "clausula-local-auth-v1"
    assert payload["base_url"] == "http://127.0.0.1:43123"
    assert payload["pid"] == os.getpid()
    assert {row["profile"] for row in payload["principals"]} == {
        McpProfile.PORTFOLIO_READ.value,
        McpProfile.ADVISOR.value,
        McpProfile.ADMIN.value,
    }
    assert all(len(row["token"]) >= 32 for row in payload["principals"])
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    path.unlink()
    assert not path.exists()


def test_store_reopen_preserves_state_and_extends_audit_chain(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = Store(home)
    account_id = LedgerService(first).create_account("broker", "persistent")
    first.record_adapter_invocation(
        adapter="daemon-test",
        actor_type="principal",
        actor_id="local-admin",
        capability="system.check",
        side_effect="local_read",
        confirmed=False,
        succeeded=True,
    )
    first_tail = first.db.execute(
        "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()[0]
    first.close()

    second = Store(home)
    try:
        assert second.db.execute(
            "SELECT id FROM accounts WHERE id=?", (account_id,)
        ).fetchone()[0] == account_id
        assert second.verify_audit_chain()["valid"] is True
        second.record_adapter_invocation(
            adapter="daemon-test",
            actor_type="principal",
            actor_id="local-admin",
            capability="system.check",
            side_effect="local_read",
            confirmed=False,
            succeeded=True,
        )
        latest = second.db.execute(
            "SELECT previous_hash,event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        assert latest["previous_hash"] == first_tail
        assert latest["event_hash"] != first_tail
        assert second.verify_audit_chain()["valid"] is True
    finally:
        second.close()
