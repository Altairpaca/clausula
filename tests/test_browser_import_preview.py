from __future__ import annotations

import base64
import hashlib
import http.client
import json
from threading import Thread
from urllib.request import Request, urlopen

from clausula import Store
from clausula.api.http import create_server
from clausula.api.import_preview import (
    MAX_IMPORT_PREVIEW_BYTES,
    MAX_IMPORT_PREVIEW_REQUEST_BYTES,
    ImportPreviewRequestError,
    preview_uploaded_csv,
)
from clausula.application import parse_csv_content, parse_csv_import


def post_json(url: str, payload: dict) -> tuple[int, dict]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_content_and_path_preview_share_identical_parser(tmp_path):
    raw = (
        b"id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        b"1,2025-01-01,2025-01-01,buy,ABC,2,100,1,usd\n"
    )
    source = tmp_path / "ledger.csv"
    source.write_bytes(raw)

    from_content = parse_csv_content(raw, recorded_at="2026-01-01")
    from_path = parse_csv_import(source, recorded_at="2026-01-01")

    assert from_content == from_path
    assert from_content.source_sha256 == hashlib.sha256(raw).hexdigest()


def test_content_parser_reports_invalid_utf8_without_filesystem_state():
    plan = parse_csv_content(b"\xff\xfe\xfa", recorded_at="2026-01-01")

    assert plan.ok is False
    assert plan.row_count == 0
    assert plan.errors[0].code == "invalid_encoding"
    assert plan.errors[0].field == "file"


def test_upload_contract_rejects_oversize_and_invalid_base64():
    try:
        preview_uploaded_csv({"content_base64": "%%%"})
    except ImportPreviewRequestError as error:
        assert "valid base64" in str(error)
    else:
        raise AssertionError("invalid base64 must fail")

    oversized = base64.b64encode(b"x" * (MAX_IMPORT_PREVIEW_BYTES + 1)).decode("ascii")
    try:
        preview_uploaded_csv({"content_base64": oversized})
    except ImportPreviewRequestError as error:
        assert "limited" in str(error)
    else:
        raise AssertionError("oversize upload must fail")


def test_anonymous_workspace_preview_processes_uploaded_bytes_not_server_paths(tmp_path):
    store = Store(tmp_path / "home")
    secret = tmp_path / "secret.csv"
    secret.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        "secret,2025-01-01,2025-01-01,deposit,CASH,0,999999,0,USD\n",
        encoding="utf-8",
    )
    supplied = str(secret).encode("utf-8")
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    before = store.db.execute("SELECT count(*) FROM transactions").fetchone()[0]
    try:
        status, body = post_json(
            f"{base}/workspace/import-preview",
            {
                "filename": "path-looking.csv",
                "content_base64": base64.b64encode(supplied).decode("ascii"),
            },
        )
        assert status == 200
        assert body["filename"] == "path-looking.csv"
        assert body["source_sha256"] == hashlib.sha256(supplied).hexdigest()
        assert body["source_sha256"] != hashlib.sha256(secret.read_bytes()).hexdigest()
        assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_workspace_preview_rejects_request_body_above_http_limit(tmp_path):
    server = create_server(Store(tmp_path / "home"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.putrequest("POST", "/workspace/import-preview")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(MAX_IMPORT_PREVIEW_REQUEST_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 413
        assert body["error"] == "preview_payload_too_large"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
