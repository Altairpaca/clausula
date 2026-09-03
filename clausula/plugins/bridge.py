from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from clausula.capabilities import CapabilityPermissionError, CapabilityRegistry

from .manifest import PluginManifest


class PluginPermissionError(PermissionError):
    """A plugin attempted an undeclared capability or permission."""


class CapabilityBridge:
    """Expose only manifest-declared capabilities to a plugin."""

    def __init__(self, registry: CapabilityRegistry, manifest: PluginManifest):
        self.registry = registry
        self.manifest = manifest

    def invoke(
        self,
        capability: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        permissions: Iterable[str] | None = None,
        confirmed: bool = False,
        dry_run: bool = False,
    ) -> Any:
        if capability not in self.manifest.capabilities:
            raise PluginPermissionError(
                f"capability not declared by plugin: {capability}"
            )
        requested = set(
            self.manifest.permissions if permissions is None else permissions
        )
        undeclared = requested - set(self.manifest.permissions)
        if undeclared:
            raise PluginPermissionError(
                f"permissions not declared by plugin: {', '.join(sorted(undeclared))}"
            )
        try:
            return self.registry.execute(
                capability,
                arguments,
                permissions=requested,
                confirmed=confirmed,
                dry_run=dry_run,
            )
        except CapabilityPermissionError:
            raise
