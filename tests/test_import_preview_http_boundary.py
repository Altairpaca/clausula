from __future__ import annotations

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from clausula import Store
from clausula.api.http import create_server


def test_workspace_import_preview_requires_application_json(tmp_path):
    server = create_server(Store(tmp_path / "home"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    request = Request(
        f"{base}/workspace/import-preview",
        data=json.dumps({"filename": "x.csv", "content_base64": "eA=="}).encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        method="POST",
    )
    try:
        try:
            urlopen(request)
        except HTTPError as error:
            body = json.loads(error.read())
            assert error.code == 415
            assert body["error"] == "unsupported_media_type"
        else:
            raise AssertionError("text/plain preview request must be rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
