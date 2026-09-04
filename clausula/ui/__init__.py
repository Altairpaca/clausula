"""Local read-only user surfaces for Clausula."""

from .execution_overlay import augment_workspace
from .workspace import workspace_document as _workspace_document


def workspace_document() -> str:
    return augment_workspace(_workspace_document())


__all__ = ["workspace_document"]
