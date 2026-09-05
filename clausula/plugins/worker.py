from __future__ import annotations

import importlib.util
import json
import os
import sys
from typing import Any


class _StdinDispatch:
    def __init__(self) -> None:
        pass

    def invoke(self, capability: str, arguments: dict[str, Any] | None = None) -> Any:
        request = {
            "type": "invoke",
            "id": "call",
            "capability": capability,
            "arguments": arguments or {},
        }
        print(json.dumps(request), flush=True)
        for line in sys.stdin:
            message = json.loads(line)
            if message.get("type") == "result" and message.get("id") == "call":
                if not message.get("ok"):
                    error = message.get("error", {})
                    raise RuntimeError(f"{error.get('type')}: {error.get('message')}")
                return message.get("result")
        raise RuntimeError("host closed the dispatch stream without a result")


def _load_plugin(plugin_file: str) -> Any:
    spec = importlib.util.spec_from_file_location("clausula_plugin", plugin_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load plugin module: {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run"):
        raise RuntimeError("plugin module must define run(dispatch)")
    return module.run


def main() -> None:
    plugin_file = os.environ.get("PLUGIN_FILE")
    if not plugin_file:
        raise RuntimeError("PLUGIN_FILE environment variable is required")
    run = _load_plugin(plugin_file)
    dispatch = _StdinDispatch()
    try:
        result = run(dispatch)
        print(json.dumps({"type": "result", "ok": True, "result": result}), flush=True)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "type": "result",
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            ),
            flush=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
