from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from clausula import Store
from clausula.capabilities import build_core_registry
from clausula.plugins import PluginManifest, PluginType
from clausula.plugins.host_policy import PluginHostPolicy, PluginHostPolicyError
from clausula.plugins.runner import (
    PluginRunner,
    PluginRunnerError,
    PluginSubprocessResult,
)

requires_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None,
    reason="bubblewrap is required to exercise the sandboxed subprocess",
)


def _reader_manifest() -> PluginManifest:
    return PluginManifest(
        name="research-reader",
        version="1.0.0",
        plugin_type=PluginType.RESEARCH,
        capabilities=("research.search",),
        permissions=("research:read",),
        side_effects=("local_read",),
    )


def _reader_policy() -> PluginHostPolicy:
    return PluginHostPolicy.from_iterables(side_effects=("local_read",))


def _reader_plugin(tmp_path: Path) -> Path:
    plugin = tmp_path / "reader_plugin.py"
    plugin.write_text(
        "def run(dispatch):\n"
        "    return dispatch.invoke('research.search', {'query': 'cash'})\n",
        encoding="utf-8",
    )
    return plugin


@requires_bwrap
def test_runner_executes_declared_read_capability_in_subprocess(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "home")
    registry = build_core_registry(store)
    runner = PluginRunner(registry=registry, host_policy=_reader_policy())
    result = runner.run(_reader_manifest(), _reader_plugin(tmp_path), timeout_seconds=20)

    assert isinstance(result, PluginSubprocessResult)
    assert result.exit_code == 0
    assert result.output.get("documents") == []


@requires_bwrap
def test_runner_rejects_undeclared_capability_in_subprocess(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    registry = build_core_registry(store)
    runner = PluginRunner(registry=registry, host_policy=_reader_policy())
    plugin = tmp_path / "bad_plugin.py"
    plugin.write_text(
        "def run(dispatch):\n"
        "    return dispatch.invoke('account.create', {'institution': 'b', 'name': 'a'})\n",
        encoding="utf-8",
    )
    manifest = PluginManifest(
        name="overreach",
        version="1.0.0",
        plugin_type=PluginType.RESEARCH,
        capabilities=("research.search",),
        permissions=("research:read",),
        side_effects=("local_read",),
    )
    with pytest.raises(PluginRunnerError):
        runner.run(manifest, plugin, timeout_seconds=20)


def test_runner_host_policy_rejects_unapproved_manifest(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    registry = build_core_registry(store)
    runner = PluginRunner(registry=registry, host_policy=PluginHostPolicy.from_iterables())
    manifest = PluginManifest(
        name="networked",
        version="1.0.0",
        plugin_type=PluginType.DATA_SOURCE,
        capabilities=("research.search",),
        permissions=("research:read",),
        network_hosts=("example.com",),
        side_effects=("external_read", "local_read"),
    )
    with pytest.raises(PluginHostPolicyError):
        runner.run(manifest, _reader_plugin(tmp_path), timeout_seconds=5)


@requires_bwrap
def test_runner_times_out_on_hung_plugin(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    registry = build_core_registry(store)
    runner = PluginRunner(registry=registry, host_policy=_reader_policy())
    plugin = tmp_path / "hung.py"
    plugin.write_text(
        "import time\n"
        "def run(dispatch):\n"
        "    time.sleep(60)\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    with pytest.raises(PluginRunnerError, match="timed out"):
        runner.run(_reader_manifest(), plugin, timeout_seconds=2)


@requires_bwrap
def test_runner_enforces_filesystem_envelope_at_os_layer(tmp_path: Path) -> None:
    store = Store(tmp_path / "home")
    registry = build_core_registry(store)
    runner = PluginRunner(registry=registry, host_policy=_reader_policy())
    plugin = tmp_path / "write_forbidden.py"
    plugin.write_text(
        "def run(dispatch):\n"
        "    try:\n"
        "        with open('/var/tmp/clausula-plugin-pwn.txt', 'w') as fh:\n"
        "            fh.write('pwned')\n"
        "        return {'wrote': True}\n"
        "    except OSError as exc:\n"
        "        return {'blocked': exc.errno}\n",
        encoding="utf-8",
    )
    result = runner.run(_reader_manifest(), plugin, timeout_seconds=20)
    assert result.exit_code == 0
    assert result.output.get("blocked") in (2, 13, 30), f"write not blocked: {result.output}"
