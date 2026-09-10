from __future__ import annotations

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from clausula import LedgerService, Store
from clausula.api.http import create_server


def post_json(url: str, payload: dict, token: str) -> tuple[int, dict]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_http_read_principal_can_preview_without_confirmation_or_persistence(tmp_path):
    store = Store(tmp_path / "home")
    account_id = LedgerService(store).create_account("broker", "main")
    source = tmp_path / "preview.csv"
    source.write_text(
        "id,date,known_at,type,ticker,quantity,amount,fee,currency,asset_type\n"
        "1,2025-01-01,2025-01-01,buy,ABC,2,100,1,usd,ETF\n",
        encoding="utf-8",
    )
    server = create_server(store)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    token = server.clausula_auth.token_for("local-read")
    before = {
        table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("artifacts", "imports", "instruments", "transactions", "legs")
    }
    try:
        status, body = post_json(
            f"{base}/capabilities/ledger.preview_csv",
            {"account_id": account_id, "path": str(source)},
            token,
        )
        assert status == 200
        assert body["ok"] is True
        instrument = body["transactions"][0]["legs"][0]["instrument"]
        assert instrument["currency"] == "USD"
        assert instrument["asset_type"] == "etf"
        after = {
            table: store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("artifacts", "imports", "instruments", "transactions", "legs")
        }
        assert after == before
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
