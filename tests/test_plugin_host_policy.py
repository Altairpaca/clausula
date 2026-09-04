from __future__ import annotations

from dataclasses import dataclass

import pytest

from clausula import Store
from clausula.capabilities import build_core_registry
from clausula.plugins import (
    PLUGIN_ENTRY_POINT_GROUP,
    PluginCatalog,
    PluginCatalogError,
    PluginHostPolicy,
    PluginHostPolicyError,
    PluginManifest,
    PluginType,
)


@dataclass
class _FakeEntryPoint:
    name: str
    value: str
    loaded: object
    group: str = PLUGIN_ENTRY_POINT_GROUP
    load_count: int = 0

    def load(self):
        self.load_count += 1
        return self.loaded


def _research_manifest(**overrides) -> PluginManifest:
    data = {
        "name": "local-research",
        "version": "1.0.0",
        "plugin_type": PluginType.RESEARCH,
        "capabilities": ("research.search",),
        "permissions": ("research:read",),
        "network_hosts": ("api.example.com",),
        "filesystem_scopes": ("research-cache",),
        "secrets": ("RESEARCH_API_TOKEN",),
        "side_effects": ("local_read",),
    }
    data.update(overrides)
    return PluginManifest(**data)


def test_catalog_discovery_does_not_import_plugin_code() -> None:
    manifest = _research_manifest()
    entry = _FakeEntryPoint("local-research", "pkg.plugin:manifest", manifest)
    catalog = PluginCatalog([entry])

    packages = catalog.packages()
    assert entry.load_count == 0
    assert packages[0].name == "local-research"
    assert packages[0].value == "pkg.plugin:manifest"

    assert catalog.load_manifest("local-research") is manifest
    assert entry.load_count == 1


def test_catalog_rejects_duplicate_or_mismatched_identity() -> None:
    manifest = _research_manifest()
    first = _FakeEntryPoint("local-research", "a:manifest", manifest)
    second = _FakeEntryPoint("local-research", "b:manifest", manifest)
    with pytest.raises(PluginCatalogError, match="duplicate"):
        PluginCatalog([first, second])

    mismatched = _FakeEntryPoint(
        "entry-name",
        "pkg:manifest",
        _research_manifest(name="manifest-name"),
    )
    with pytest.raises(PluginCatalogError, match="does not match"):
        PluginCatalog([mismatched]).load_manifest("entry-name")


def test_host_policy_authorizes_only_explicit_resource_envelope(tmp_path) -> None:
    manifest = _research_manifest()
    registry = build_core_registry(Store(tmp_path / "home"))
    policy = PluginHostPolicy.from_iterables(
        network_hosts=("api.example.com",),
        filesystem_scopes=("research-cache",),
        secrets=("RESEARCH_API_TOKEN",),
        side_effects=("local_read",),
    )

    policy.authorize(manifest, registry=registry)

    denied = PluginHostPolicy.from_iterables(
        filesystem_scopes=("research-cache",),
        secrets=("RESEARCH_API_TOKEN",),
        side_effects=("local_read",),
    )
    with pytest.raises(PluginHostPolicyError, match="network hosts"):
        denied.authorize(manifest, registry=registry)


def test_host_policy_detects_manifest_permission_and_side_effect_underdeclaration(tmp_path) -> None:
    registry = build_core_registry(Store(tmp_path / "home"))
    policy = PluginHostPolicy.from_iterables(side_effects=("local_read",))

    missing_permission = _research_manifest(
        permissions=(),
        network_hosts=(),
        filesystem_scopes=(),
        secrets=(),
    )
    with pytest.raises(PluginHostPolicyError, match="undeclared permissions"):
        policy.authorize(missing_permission, registry=registry)

    missing_effect = _research_manifest(
        network_hosts=(),
        filesystem_scopes=(),
        secrets=(),
        side_effects=(),
    )
    with pytest.raises(PluginHostPolicyError, match="undeclared side effect"):
        PluginHostPolicy().authorize(missing_effect, registry=registry)
