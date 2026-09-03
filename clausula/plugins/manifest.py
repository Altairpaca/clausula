from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PluginType(StrEnum):
    DATA_SOURCE = "data_source"
    ANALYTICS = "analytics"
    RESEARCH = "research"
    POLICY = "policy"
    ACTION = "action"


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    plugin_type: PluginType
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    network_hosts: tuple[str, ...] = ()
    filesystem_scopes: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    min_core_version: str = "0.1.0"

    def __post_init__(self) -> None:
        for field in ("name", "version", "min_core_version"):
            if not getattr(self, field).strip():
                raise ValueError(f"plugin {field} cannot be empty")
        if not self.capabilities:
            raise ValueError("plugin must declare at least one capability")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("plugin capabilities must be unique")
        for capability in self.capabilities:
            namespace, separator, operation = capability.partition(".")
            if not namespace or not separator or not operation:
                raise ValueError("plugin capability must use namespace.operation")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("plugin permissions must be unique")
        if self.plugin_type is PluginType.ACTION and "external_write" in self.side_effects:
            raise ValueError("autonomous external writes are not enabled for action plugins")
