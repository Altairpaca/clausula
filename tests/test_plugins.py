from __future__ import annotations

import pytest

from clausula import Store
from clausula.capabilities import (
    CapabilityPermissionError,
    ConfirmationRequired,
    build_core_registry,
)
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


def test_plugin_bridge_uses_fixed_manifest_envelope(tmp_path) -> None:
    registry = build_core_registry(Store(tmp_path / "home"))
    manifest = PluginManifest(
        name="local-research",
        version="1.0.0",
        plugin_type=PluginType.RESEARCH,
        capabilities=("research.search",),
        permissions=("research:read",),
    )
    bridge = CapabilityBridge(registry, manifest)

    assert bridge.permissions == frozenset({"research:read"})
    assert bridge.invoke("research.search", {"query": "cash"}) == {
        "documents": [],
        "claims": [],
        "evidence": [],
        "theses": [],
    }
    with pytest.raises(PluginPermissionError, match="not declared"):
        bridge.invoke("account.create", {"institution": "b", "name": "a"})


def test_plugin_cannot_self_confirm_a_host_approved_write(tmp_path) -> None:
    registry = build_core_registry(Store(tmp_path / "home"))
    manifest = PluginManifest(
        name="account-importer",
        version="1.0.0",
        plugin_type=PluginType.ACTION,
        capabilities=("account.create",),
        permissions=("ledger:write",),
    )
    bridge = CapabilityBridge(registry, manifest)
    arguments = {"institution": "broker", "name": "main"}

    # Dry-run is safe and proves the manifest has the needed permission.
    assert bridge.invoke("account.create", arguments, dry_run=True)["would_execute"] is True
    # The plugin-facing API has no `confirmed` or per-call `permissions` input;
    # an actual write must be approved by a future trusted host path.
    with pytest.raises(ConfirmationRequired):
        bridge.invoke("account.create", arguments)


def test_manifest_permission_still_cannot_bypass_registry_requirements(tmp_path) -> None:
    registry = build_core_registry(Store(tmp_path / "home"))
    manifest = PluginManifest(
        name="underprivileged",
        version="1.0.0",
        plugin_type=PluginType.RESEARCH,
        capabilities=("research.search",),
        permissions=(),
    )
    bridge = CapabilityBridge(registry, manifest)
    with pytest.raises(CapabilityPermissionError):
        bridge.invoke("research.search", {"query": "cash"})
