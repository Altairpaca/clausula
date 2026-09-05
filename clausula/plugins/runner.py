"""Host-side runner that executes a plugin in a sandboxed subprocess."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from clausula.capabilities import CapabilityRegistry
from clausula.plugins.bridge import CapabilityBridge
from clausula.plugins.host_policy import PluginHostPolicy
from clausula.plugins.manifest import PluginManifest


class PluginRunnerError(RuntimeError):
    pass


class PluginSubprocessResult:
    def __init__(self, *, exit_code: int, output: Any, stderr: str) -> None:
        self.exit_code = exit_code
        self.output = output
        self.stderr = stderr


def _bwrap_command(plugin_file: Path, allowed_dirs: list[str]) -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = str(repo_root) + (os.pathsep + pythonpath if pythonpath else "")
    command = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "PYTHONPATH", pythonpath,
        "--setenv", "PLUGIN_FILE", str(plugin_file),
    ]
    for directory in allowed_dirs:
        command += ["--bind", directory, directory]
    command += ["--ro-bind", str(plugin_file), str(plugin_file)]
    command += [sys.executable, "-m", "clausula.plugins.worker"]
    return command


class PluginRunner:
    """Authorize a manifest, then run the plugin in a bwrap-sandboxed subprocess.

    The plugin's ``run(dispatch)`` executes inside the sandbox. Each
    ``dispatch.invoke`` is relayed to this host over stdio JSON lines, executed
    through a real CapabilityBridge with the manifest's fixed permission
    envelope, and the result is returned to the sandbox. Confirmation-required
    writes fail closed because the subprocess has no confirmation authority.
    bwrap independently enforces the network/filesystem/secret envelope.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        host_policy: PluginHostPolicy | None = None,
        *,
        bridge: CapabilityBridge | None = None,
    ) -> None:
        self.registry = registry
        self.host_policy = host_policy or PluginHostPolicy()
        self.bridge = bridge

    def run(
        self,
        manifest: PluginManifest,
        plugin_file: str | Path,
        *,
        timeout_seconds: float = 30.0,
        allowed_dirs: list[str] | None = None,
    ) -> PluginSubprocessResult:
        self.host_policy.authorize(manifest, registry=self.registry)
        plugin_path = Path(plugin_file).resolve()
        if not plugin_path.is_file():
            raise PluginRunnerError(f"plugin file not found: {plugin_path}")
        bridge = self.bridge or CapabilityBridge(self.registry, manifest)
        handled: set[str] = set()

        def handle_invoke(request: dict[str, Any]) -> None:
            request_id = str(request.get("id") or "")
            capability = str(request.get("capability") or "")
            call_args = request.get("arguments") or {}

            def respond(outcome: dict[str, Any]) -> None:
                if request_id not in handled:
                    handled.add(request_id)
                    process.stdin.write(
                        json.dumps({"type": "result", "id": request_id, **outcome})
                        + "\n"
                    )
                    process.stdin.flush()

            try:
                result = bridge.invoke(capability, call_args)
                respond({"ok": True, "result": result})
            except Exception as exc:
                respond(
                    {
                        "ok": False,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                )

        process = subprocess.Popen(
            _bwrap_command(plugin_path, allowed_dirs or []),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        main_result: dict[str, Any] | None = None
        error_detail: str | None = None

        def pump_stdout() -> None:
            nonlocal main_result, error_detail
            for line in process.stdout or []:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    error_detail = f"malformed output: {line[:200]}"
                    continue
                if message.get("type") == "invoke":
                    handle_invoke(message)
                elif message.get("type") == "result" and message.get("id") is None:
                    main_result = message

        stdout_thread = threading.Thread(target=pump_stdout, daemon=True)
        stdout_thread.start()
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise PluginRunnerError(
                f"plugin timed out after {timeout_seconds}s: {manifest.name}"
            )
        stderr_text = process.stderr.read() if process.stderr else ""
        stdout_thread.join(timeout=5)
        if error_detail is not None:
            raise PluginRunnerError(error_detail)
        if exit_code != 0:
            raise PluginRunnerError(
                f"plugin exited with code {exit_code}: {stderr_text[-500:]}"
            )
        if main_result is None:
            raise PluginRunnerError(
                f"plugin produced no result: {stderr_text[-500:]}"
            )
        if not main_result.get("ok"):
            error = main_result.get("error", {})
            raise PluginRunnerError(
                f"plugin invocation failed: {error.get('type')}: {error.get('message')}"
            )
        return PluginSubprocessResult(
            exit_code=exit_code,
            output=main_result.get("result"),
            stderr=stderr_text,
        )
