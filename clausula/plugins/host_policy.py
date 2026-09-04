from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from clausula.capabilities import CapabilityRegistry

from .manifest import PluginManifest


class PluginHostPolicyError(PermissionError):
    """A plugin manifest exceeds the host-approved resource envelope."""


@dataclass(frozen=True, slots=True)
class PluginHostPolicy:
    """Declarative host authorization before any plugin runtime is started.

    This object does not pretend to be an OS sandbox. It validates that a plugin's
    declared network/filesystem/secret/side-effect requirements are within an
    explicit host allow-list and, when a registry is supplied, that every declared
    capability has enough manifest permission and an explicitly declared side
    effect. A process sandbox must enforce the same envelope at runtime.
    """

    network_hosts: frozenset[str] = field(default_factory=frozenset)
    filesystem_scopes: frozenset[str] = field(default_factory=frozenset)
    secrets: frozenset[str] = field(default_factory=frozenset)
    side_effects: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_iterables(
        cls,
        *,
        network_hosts: Iterable[str] = (),
        filesystem_scopes: Iterable[str] = (),
        secrets: Iterable[str] = (),
        side_effects: Iterable[str] = (),
    ) -> "PluginHostPolicy":
        return cls(
            frozenset(network_hosts),
            frozenset(filesystem_scopes),
            frozenset(secrets),
            frozenset(side_effects),
        )

    def authorize(
        self,
        manifest: PluginManifest,
        *,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        violations: list[str] = []
        self._check_subset(
            "network hosts", manifest.network_hosts, self.network_hosts, violations
        )
        self._check_subset(
            "filesystem scopes",
            manifest.filesystem_scopes,
            self.filesystem_scopes,
            violations,
        )
        self._check_subset("secrets", manifest.secrets, self.secrets, violations)
        self._check_subset(
            "side effects", manifest.side_effects, self.side_effects, violations
        )

        if registry is not None:
            declared_permissions = set(manifest.permissions)
            declared_effects = set(manifest.side_effects)
            for capability in manifest.capabilities:
                spec = registry.get(capability)
                missing_permissions = set(spec.permissions) - declared_permissions
                if missing_permissions:
                    violations.append(
                        f"capability {capability} requires undeclared permissions: "
                        + ", ".join(sorted(missing_permissions))
                    )
                if spec.side_effect.value != "none" and spec.side_effect.value not in declared_effects:
                    violations.append(
                        f"capability {capability} has undeclared side effect: {spec.side_effect.value}"
                    )

        if violations:
            raise PluginHostPolicyError("; ".join(violations))

    @staticmethod
    def _check_subset(
        label: str,
        requested: Iterable[str],
        allowed: frozenset[str],
        violations: list[str],
    ) -> None:
        excess = set(requested) - set(allowed)
        if excess:
            violations.append(f"{label} not approved by host: {', '.join(sorted(excess))}")
