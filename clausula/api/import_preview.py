from __future__ import annotations

import base64
import binascii
from typing import Any, Mapping

from clausula.application import parse_csv_content


MAX_IMPORT_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_IMPORT_PREVIEW_REQUEST_BYTES = 3 * 1024 * 1024


class ImportPreviewRequestError(ValueError):
    pass


def preview_uploaded_csv(payload: Mapping[str, Any]) -> dict[str, Any]:
    unexpected = set(payload) - {"filename", "content_base64"}
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

    result = parse_csv_content(raw).as_dict()
    result["filename"] = filename
    result["upload_bytes"] = len(raw)
    return result
