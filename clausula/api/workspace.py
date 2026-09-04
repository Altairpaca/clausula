from __future__ import annotations

import argparse
import webbrowser

from clausula.store import Store

from .http import create_server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="clausula-workspace",
        description="Launch the local read-only Clausula Capital Cockpit.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the workspace URL in the default browser.",
    )
    args = parser.parse_args(argv)

    server = create_server(Store())
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Clausula Capital Cockpit: {url}")
    print("Local read-only projection. Press Ctrl-C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
