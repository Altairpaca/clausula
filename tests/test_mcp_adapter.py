from __future__ import annotations

import pytest

from clausula import Store
from clausula.adapters.mcp import McpAdapter, McpProfile
from clausula.capabilities import CapabilityPermissionError


def test_mcp_profiles_project_only_allowed_registry_tools(tmp_path) -> None:
    store = Store(tmp_path / "home")
    adapter = McpAdapter(store)

    tools = adapter.list_tools(McpProfile.RESEARCH_READ)

    assert all("research:" in permission for tool in tools for permission in tool.permissions)
    assert any(tool.name == "research.search" for tool in tools)
    assert not any(tool.name == "account.create" for tool in tools)


def test_mcp_call_uses_structured_registry_and_profile_permissions(tmp_path) -> None:
    store = Store(tmp_path / "home")
    adapter = McpAdapter(store)

    assert adapter.call(
        McpProfile.RESEARCH_READ,
        "research.search",
        {"query": "cash"},
        agent_id="research-client",
    ) == {
        "documents": [],
        "claims": [],
        "evidence": [],
        "theses": [],
    }
    with pytest.raises(CapabilityPermissionError):
        adapter.call(
            McpProfile.RESEARCH_READ,
            "account.create",
            {"institution": "broker", "name": "main"},
        )
    event = store.db.execute(
        "SELECT * FROM audit_events WHERE operation='mcp.invoke' ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    assert event["actor_type"] == "agent"
    assert event["actor_id"] == "research-client"
