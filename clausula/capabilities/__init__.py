from .core import build_core_registry as _build_core_registry
from .execution import register_execution_capabilities
from .market_intelligence import register_market_intelligence_capabilities
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
    # Execution, market-intelligence, and decision-workspace projections currently
    # use the local audit/provenance-backed SQLite adapter. Non-SQLite repository
    # implementations retain the canonical core surface.
    if hasattr(repository, "db"):
        register_execution_capabilities(registry, repository)
        register_market_intelligence_capabilities(registry, repository)
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
