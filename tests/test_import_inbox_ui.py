from __future__ import annotations

from clausula.ui import workspace_document


def test_workspace_contains_browser_safe_preview_only_import_inbox():
    document = workspace_document()

    assert 'id="import-inbox-panel"' in document
    assert 'id="import-file"' in document
    assert 'type="file"' in document
    assert 'accept=".csv,text/csv"' in document
    assert 'fetch("/workspace/import-preview"' in document
    assert "content_base64" in document
    assert "PREVIEW ONLY" in document
    assert "No server filesystem path is accepted" in document

    # The browser inbox is intentionally not an import/commit surface.
    assert "/capabilities/ledger.import_csv" not in document
    assert 'name="path"' not in document
