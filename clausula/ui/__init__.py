"""Local read-only user surfaces for Clausula."""

from .decision_overlay import augment_decision_workspace
from .execution_overlay import augment_workspace
from .workspace import workspace_document as _workspace_document


def workspace_document() -> str:
    document = augment_workspace(_workspace_document())
    return augment_decision_workspace(document)


__all__ = ["workspace_document"]
