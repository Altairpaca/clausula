from __future__ import annotations

import pytest

from clausula import Store
from clausula.capabilities import CapabilityPermissionError, build_core_registry
from clausula.plugins import PluginManifest, PluginPermissionError, PluginType
from clausula.plugins.bridge import CapabilityBridge


def test_plugin_manifest_requires_declared_capabilities_and_permissions() -> None:
    manifest = PluginManifest(
        name="local-research",
        version="1.0.0",
        plugin_type=PluginType.RESEARCH,
        capabilities=("research.search",),
        permissions=("research:read",),
    )

    assert manifest.capabilities == ("research.search",)
    assert manifest.network_hosts == ()

    with pytest.raises(ValueError, match="capability"):
        PluginManifest(
            name="broken",
            version="1.0.0",
            plugin_type=PluginType.RESEARCH,
            capabilities=("not-a-capability",),
            permissions=("research:read",),
        )


def test_plugin_bridge_cannot_invoke_undeclared_or_unpermitted_capability(tmp_path) -> None:
    registry = build_core_registry(Store(tmp_path / "home"))
    manifest = PluginManifest(
        name="local-research",
        version="1.0.0",
        plugin_type=PluginType.RESEARCH,
        capabilities=("research.search",),
        permissions=("research:read",),
    )
    bridge = CapabilityBridge(registry, manifest)

    assert bridge.invoke("research.search", {"query": "cash"}) == {
        "documents": [],
        "claims": [],
        "evidence": [],
        "theses": [],
    }
    with pytest.raises(PluginPermissionError, match="not declared"):
        bridge.invoke("account.create", {"institution": "b", "name": "a"})
    with pytest.raises(CapabilityPermissionError):
        bridge.invoke("research.search", {"query": "cash"}, permissions=())
