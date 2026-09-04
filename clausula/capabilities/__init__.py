from .core import build_core_registry as _build_core_registry
from .execution import register_execution_capabilities
from .market_intelligence import register_market_intelligence_capabilities
from .research_ingest import register_research_ingestion_capabilities
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
    # Local projections add audit/provenance-backed capabilities without changing
    # the portable repository protocol. Non-SQLite repositories retain core surfaces.
    if hasattr(repository, "db"):
        register_execution_capabilities(registry, repository)
        register_market_intelligence_capabilities(registry, repository)
        register_research_ingestion_capabilities(registry, repository)
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
