from __future__ import annotations

from clausula.ui import workspace_document


def test_workspace_contains_account_aware_preview_only_import_inbox():
    document = workspace_document()

    assert 'id="import-inbox-panel"' in document
    assert 'id="import-account"' in document
    assert "Account UUID" in document
    assert 'id="import-file"' in document
    assert 'type="file"' in document
    assert 'accept=".csv,text/csv"' in document
    assert 'fetch("/workspace/import-preview"' in document
    assert "account_id: accountId" in document
    assert "content_base64" in document
    assert "PREVIEW ONLY" in document
    assert "ALREADY IMPORTED" in document
    assert "CONFLICT" in document
    assert "NEW" in document
    assert "reads no caller-supplied server path" in document

    # The browser inbox remains intentionally unable to commit/import.
    assert "/capabilities/ledger.import_csv" not in document
    assert 'name="path"' not in document
    assert "X-Clausula-Confirmation" not in document
    assert "Authorization" not in document
    assert "existing_transaction_ids" not in document
