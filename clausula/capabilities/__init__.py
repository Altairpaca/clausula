from .core import build_core_registry as _build_core_registry
from .execution import register_execution_capabilities
from .workspace import register_decision_workspace_capabilities
from .registry import (
    CapabilityError,
    CapabilityPermissionError,
    CapabilityRegistry,
    CapabilitySpec,
    ConfirmationRequired,
    SideEffect,
)


def build_core_registry(repository):
    registry = _build_core_registry(repository)
    # Execution and decision-workspace projections currently use the local
    # audit-backed SQLite adapter. Non-SQLite repositories retain core surfaces.
    if hasattr(repository, "db"):
        register_execution_capabilities(registry, repository)
        register_decision_workspace_capabilities(registry, repository)
    return registry


__all__ = [
    "CapabilityError",
    "CapabilityPermissionError",
    "CapabilityRegistry",
    "CapabilitySpec",
    "ConfirmationRequired",
    "SideEffect",
    "build_core_registry",
]
