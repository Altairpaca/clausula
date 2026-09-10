from __future__ import annotations

import base64
import hashlib
import http.client
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from clausula import LedgerService, Store
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
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def encoded(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


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

    oversized = encoded(b"x" * (MAX_IMPORT_PREVIEW_BYTES + 1))
    try:
        preview_uploaded_csv({"content_base64": oversized})
    except ImportPreviewRequestError as error:
        assert "limited" in str(error)
    else:
        raise AssertionError("oversize upload must fail")


def test_anonymous_workspace_preview_requires_real_account(tmp_path):
    store = Store(tmp_path / "home")
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    raw = b"id,date,type,ticker,quantity,amount,fee,currency\n"
    try:
        status, body = post_json(
            f"{base}/workspace/import-preview",
            {"filename": "empty.csv", "content_base64": encoded(raw)},
        )
        assert status == 400
        assert body["error"] == "invalid_import_preview"
        assert "account_id is required" in body["message"]

        status, body = post_json(
            f"{base}/workspace/import-preview",
            {
                "account_id": "00000000-0000-4000-8000-000000000000",
                "filename": "empty.csv",
                "content_base64": encoded(raw),
            },
        )
        assert status == 400
        assert body["error"] == "invalid_import_preview"
        assert "unknown account" in body["message"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_anonymous_workspace_preview_processes_uploaded_bytes_not_server_paths(tmp_path):
    store = Store(tmp_path / "home")
    account_id = LedgerService(store).create_account("broker", "main")
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
                "account_id": account_id,
                "filename": "path-looking.csv",
                "content_base64": encoded(supplied),
            },
        )
        assert status == 200
        assert body["filename"] == "path-looking.csv"
        assert body["source_sha256"] == hashlib.sha256(supplied).hexdigest()
        assert body["source_sha256"] != hashlib.sha256(secret.read_bytes()).hexdigest()
        assert body["reconciliation"]["account_id"] == account_id
        assert store.db.execute("SELECT count(*) FROM transactions").fetchone()[0] == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_preview_classifies_duplicate_new_and_hides_transaction_ids(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    accepted = tmp_path / "accepted.csv"
    accepted.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency,description\n"
        "old,2025-01-01,2025-01-01,buy,ABC,2,100,1,USD,first export\n",
        encoding="utf-8",
    )
    service.import_csv(account_id, accepted)
    raw = (
        "id,date,known_at,type,ticker,quantity,amount,fee,currency,description\n"
        "old,2025-01-01,2025-01-01,buy,ABC,2,100,1,USD,later description\n"
        "new,2025-01-02,2025-01-02,deposit,CASH,0,50,0,USD,new cash\n"
    ).encode("utf-8")
    before = {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "transactions", "legs")
    }

    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = post_json(
            f"{base}/workspace/import-preview",
            {
                "account_id": account_id,
                "filename": "later.csv",
                "content_base64": encoded(raw),
            },
        )
        assert status == 200
        assert body["ok"] is True
        assert body["reconciliation"] == {
            "account_id": account_id,
            "new": 1,
            "duplicate_exact": 1,
            "conflict_external_id": 0,
        }
        assert [item["import_status"] for item in body["transactions"]] == [
            "duplicate_exact",
            "new",
        ]
        assert "existing_transaction_ids" not in json.dumps(body)
        assert {
            table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in before
        } == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_preview_surfaces_conflict_without_writes(tmp_path):
    store = Store(tmp_path / "home")
    service = LedgerService(store)
    account_id = service.create_account("broker", "main")
    accepted = tmp_path / "accepted.csv"
    accepted.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        "trade,2025-01-01,2025-01-01,buy,ABC,2,100,1,USD\n",
        encoding="utf-8",
    )
    service.import_csv(account_id, accepted)
    conflict = (
        "id,date,known_at,type,ticker,quantity,amount,fee,currency\n"
        "trade,2025-01-01,2025-01-01,buy,ABC,3,150,1,USD\n"
    ).encode("utf-8")
    before = store.db.execute("SELECT count(*) FROM transactions").fetchone()[0]

    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = post_json(
            f"{base}/workspace/import-preview",
            {
                "account_id": account_id,
                "filename": "conflict.csv",
                "content_base64": encoded(conflict),
            },
        )
        assert status == 200
        assert body["ok"] is False
        assert body["reconciliation"]["conflict_external_id"] == 1
        assert body["transactions"][0]["import_status"] == "conflict_external_id"
        assert body["errors"][-1]["code"] == "conflict_external_id"
        assert "existing_transaction_ids" not in json.dumps(body)
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
