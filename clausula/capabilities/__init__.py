from .core import build_core_registry as _build_core_registry
from .equity_monitor import register_equity_monitor_capabilities
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
    # Local audit/provenance-backed projections extend the portable core without
    # making monitoring, research extraction, or configuration state canonical
    # financial truth.
    if hasattr(repository, "db"):
        register_execution_capabilities(registry, repository)
        register_market_intelligence_capabilities(registry, repository)
        register_research_ingestion_capabilities(registry, repository)
        register_equity_monitor_capabilities(registry, repository)
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
