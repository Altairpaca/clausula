from __future__ import annotations

import base64
import binascii
from typing import Any, Mapping

from clausula.application import parse_csv_content
from clausula.application.ledger_reconciled import reconcile_csv_plan


MAX_IMPORT_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_IMPORT_PREVIEW_REQUEST_BYTES = 3 * 1024 * 1024


class ImportPreviewRequestError(ValueError):
    pass


def _decode_uploaded_csv(payload: Mapping[str, Any]) -> tuple[str, bytes]:
    unexpected = set(payload) - {"account_id", "filename", "content_base64"}
    if unexpected:
        raise ImportPreviewRequestError(
            f"unknown preview fields: {', '.join(sorted(unexpected))}"
        )
    filename = str(payload.get("filename") or "upload.csv").strip() or "upload.csv"
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ImportPreviewRequestError("content_base64 is required")
    if len(encoded) > ((MAX_IMPORT_PREVIEW_BYTES + 2) // 3) * 4 + 4:
        raise ImportPreviewRequestError(
            f"CSV preview is limited to {MAX_IMPORT_PREVIEW_BYTES} bytes"
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImportPreviewRequestError("content_base64 is not valid base64") from exc
    if len(raw) > MAX_IMPORT_PREVIEW_BYTES:
        raise ImportPreviewRequestError(
            f"CSV preview is limited to {MAX_IMPORT_PREVIEW_BYTES} bytes"
        )
    return filename, raw


def _browser_safe_reconciliation(result: dict[str, Any]) -> dict[str, Any]:
    """Remove canonical transaction identifiers from the anonymous projection."""

    transactions = []
    for transaction in result.get("transactions", ()):
        item = dict(transaction)
        item.pop("existing_transaction_ids", None)
        transactions.append(item)
    return {**result, "transactions": transactions}


def preview_uploaded_csv(
    payload: Mapping[str, Any], repository=None
) -> dict[str, Any]:
    """Preview uploaded CSV bytes; optionally reconcile against one account.

    The repository-free mode remains useful for parser/size unit tests. The
    browser HTTP route always supplies the repository and therefore requires an
    account ID before it can claim import status.
    """

    filename, raw = _decode_uploaded_csv(payload)
    plan = parse_csv_content(raw)
    if repository is None:
        result = plan.as_dict()
    else:
        account_id = payload.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            raise ImportPreviewRequestError("account_id is required")
        try:
            result = reconcile_csv_plan(repository, account_id.strip(), plan)
        except (KeyError, TypeError, ValueError) as exc:
            raise ImportPreviewRequestError(str(exc)) from exc
        result = _browser_safe_reconciliation(result)
    result["filename"] = filename
    result["upload_bytes"] = len(raw)
    return result
