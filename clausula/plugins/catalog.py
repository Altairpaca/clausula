from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any, Iterable

from .manifest import PluginManifest


PLUGIN_ENTRY_POINT_GROUP = "clausula.plugins"


@dataclass(frozen=True, slots=True)
class PluginPackage:
    """Import-free metadata for one discovered plugin entry point."""

    name: str
    value: str
    group: str
    distribution: str | None = None


class PluginCatalogError(RuntimeError):
    pass


class PluginCatalog:
    """Discover plugin packages without importing plugin code.

    Discovery enumerates entry-point metadata only. `load_manifest` is an explicit
    trust transition and is the first operation that may import third-party code.
    A host should authorize the returned manifest before starting any plugin
    runtime/process.
    """

    def __init__(self, entries: Iterable[Any] | None = None) -> None:
        if entries is None:
            entries = metadata.entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
        self._entries = tuple(
            entry
            for entry in entries
            if getattr(entry, "group", PLUGIN_ENTRY_POINT_GROUP)
            == PLUGIN_ENTRY_POINT_GROUP
        )
        names = [str(entry.name) for entry in self._entries]
        if len(set(names)) != len(names):
            raise PluginCatalogError("duplicate Clausula plugin entry-point name")

    def packages(self) -> list[PluginPackage]:
        result: list[PluginPackage] = []
        for entry in sorted(self._entries, key=lambda item: str(item.name)):
            distribution = None
            dist = getattr(entry, "dist", None)
            if dist is not None:
                try:
                    distribution = dist.metadata.get("Name")
                except (AttributeError, KeyError, TypeError):
                    distribution = None
            result.append(
                PluginPackage(
                    name=str(entry.name),
                    value=str(entry.value),
                    group=str(getattr(entry, "group", PLUGIN_ENTRY_POINT_GROUP)),
                    distribution=None if distribution is None else str(distribution),
                )
            )
        return result

    def load_manifest(self, name: str) -> PluginManifest:
        """Explicitly import one selected entry point and return its manifest."""

        matches = [entry for entry in self._entries if str(entry.name) == name]
        if not matches:
            raise KeyError(f"unknown plugin package: {name}")
        if len(matches) != 1:
            raise PluginCatalogError(f"ambiguous plugin package: {name}")
        loaded = matches[0].load()
        candidate: Any
        if isinstance(loaded, PluginManifest):
            candidate = loaded
        elif hasattr(loaded, "manifest"):
            candidate = getattr(loaded, "manifest")
            candidate = candidate() if callable(candidate) else candidate
        elif callable(loaded):
            candidate = loaded()
        else:
            candidate = loaded
        if not isinstance(candidate, PluginManifest):
            raise PluginCatalogError(
                f"plugin entry point {name} did not provide PluginManifest"
            )
        if candidate.name != name:
            raise PluginCatalogError(
                f"plugin manifest name {candidate.name!r} does not match entry point {name!r}"
            )
        return candidate
