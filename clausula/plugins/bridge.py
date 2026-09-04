from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from clausula.capabilities import CapabilityRegistry

from .manifest import PluginManifest


class PluginPermissionError(PermissionError):
    """A plugin attempted an undeclared capability."""


class CapabilityBridge:
    """Expose a fixed manifest capability/permission envelope to a plugin.

    The plugin cannot choose a permission set per invocation and cannot assert
    confirmation. Confirmation-required writes therefore fail closed until the
    trusted host/daemon provides a separate approval path outside plugin code.
    """

    def __init__(self, registry: CapabilityRegistry, manifest: PluginManifest):
        self.registry = registry
        self.manifest = manifest
        self.permissions = frozenset(manifest.permissions)

    def invoke(
        self,
        capability: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> Any:
        if capability not in self.manifest.capabilities:
            raise PluginPermissionError(
                f"capability not declared by plugin: {capability}"
            )
        return self.registry.execute(
            capability,
            arguments,
            permissions=self.permissions,
            confirmed=False,
            dry_run=dry_run,
        )
