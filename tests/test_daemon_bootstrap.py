from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

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
