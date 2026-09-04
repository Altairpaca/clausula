"""Controlled extension contracts for outer-layer plugins."""

from .bridge import CapabilityBridge, PluginPermissionError
from .catalog import (
    PLUGIN_ENTRY_POINT_GROUP,
    PluginCatalog,
    PluginCatalogError,
    PluginPackage,
)
from .host_policy import PluginHostPolicy, PluginHostPolicyError
from .manifest import PluginManifest, PluginType

__all__ = [
    "CapabilityBridge",
    "PLUGIN_ENTRY_POINT_GROUP",
    "PluginCatalog",
    "PluginCatalogError",
    "PluginHostPolicy",
    "PluginHostPolicyError",
    "PluginManifest",
    "PluginPackage",
    "PluginPermissionError",
    "PluginType",
]
