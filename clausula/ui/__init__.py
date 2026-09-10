"""Local read-only user surfaces for Clausula."""

from .decision_overlay import augment_decision_workspace
from .equity_overlay import augment_equity_monitor
from .execution_overlay import augment_workspace
from .import_inbox import augment_import_inbox
from .workspace import workspace_document as _workspace_document


def workspace_document() -> str:
    document = augment_workspace(_workspace_document())
    document = augment_decision_workspace(document)
    document = augment_equity_monitor(document)
    return augment_import_inbox(document)


__all__ = ["workspace_document"]
