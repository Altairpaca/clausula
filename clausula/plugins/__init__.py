"""Controlled extension contracts for outer-layer plugins."""

from .manifest import PluginManifest, PluginType
from .bridge import CapabilityBridge, PluginPermissionError

__all__ = [
    "CapabilityBridge",
    "PluginManifest",
    "PluginPermissionError",
    "PluginType",
]
