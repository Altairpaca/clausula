from __future__ import annotations

import pytest

from clausula import Store
from clausula.adapters.mcp import McpAdapter, McpProfile
from clausula.capabilities import CapabilityPermissionError, ConfirmationRequired


def test_mcp_profile_and_actor_are_bound_at_construction(tmp_path) -> None:
    store = Store(tmp_path / "home")
    adapter = McpAdapter(
        store,
        profile=McpProfile.RESEARCH_READ,
        agent_id="research-client",
    )

    tools = adapter.list_tools()

    assert adapter.profile is McpProfile.RESEARCH_READ
    assert adapter.agent_id == "research-client"
    assert all("research:" in permission for tool in tools for permission in tool.permissions)
    assert any(tool.name == "research.search" for tool in tools)
    assert not any(tool.name == "account.create" for tool in tools)


def test_mcp_call_uses_bound_profile_and_actor_identity(tmp_path) -> None:
    store = Store(tmp_path / "home")
    adapter = McpAdapter(
        store,
        profile=McpProfile.RESEARCH_READ,
        agent_id="research-client",
    )

    assert adapter.call("research.search", {"query": "cash"}) == {
        "documents": [],
        "claims": [],
        "evidence": [],
        "theses": [],
    }
    with pytest.raises(CapabilityPermissionError):
        adapter.call(
            "account.create",
            {"institution": "broker", "name": "main"},
        )
    event = store.db.execute(
        "SELECT * FROM audit_events WHERE operation='mcp.invoke' ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    assert event["actor_type"] == "agent"
    assert event["actor_id"] == "research-client"


def test_mcp_cannot_self_confirm_write_even_when_bound_admin(tmp_path) -> None:
    store = Store(tmp_path / "home")
    adapter = McpAdapter(
        store,
        profile=McpProfile.ADMIN,
        agent_id="admin-agent",
    )
    arguments = {"institution": "broker", "name": "main"}

    assert adapter.call("account.create", arguments, dry_run=True)["would_execute"] is True
    with pytest.raises(ConfirmationRequired):
        adapter.call("account.create", arguments)
    assert store.db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0


def test_mcp_rejects_empty_bound_actor_identity(tmp_path) -> None:
    with pytest.raises(ValueError, match="agent_id"):
        McpAdapter(
            Store(tmp_path / "home"),
            profile=McpProfile.RESEARCH_READ,
            agent_id=" ",
        )
