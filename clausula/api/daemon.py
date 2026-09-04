from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import IO
import webbrowser

from clausula.store import Store

from .auth import LocalAuthRegistry
from .http import create_server


class DaemonAlreadyRunning(RuntimeError):
    pass


class DaemonLease:
    """Best-effort OS file lock preventing two Clausula daemon writers per home."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._stream: IO[str] | None = None

    def acquire(self) -> "DaemonLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "posix":
                import fcntl

                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DaemonAlreadyRunning(
                        f"another Clausula daemon owns {self.path.parent}"
                    ) from exc
            elif os.name == "nt":  # pragma: no cover - exercised on Windows locally
                import msvcrt

                stream.seek(0)
                if not stream.read(1):
                    stream.seek(0)
                    stream.write("0")
                    stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise DaemonAlreadyRunning(
                        f"another Clausula daemon owns {self.path.parent}"
                    ) from exc
            else:  # pragma: no cover - unknown platforms require local validation
                raise RuntimeError("daemon lease is unsupported on this operating system")
            stream.seek(0)
            stream.truncate()
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
            self._stream = stream
            return self
        except Exception:
            stream.close()
            raise

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":  # pragma: no cover
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            stream.close()
            self._stream = None
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> "DaemonLease":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def write_auth_manifest(
    path: str | Path,
    auth: LocalAuthRegistry,
    *,
    base_url: str,
) -> Path:
    """Atomically materialize daemon bootstrap credentials outside canonical state."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.parent.chmod(0o700)
    except OSError:
        pass
    payload = auth.credential_manifest() | {
        "base_url": base_url,
        "pid": os.getpid(),
    }
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        return destination
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def default_home() -> Path:
    return Path(os.environ.get("CLAUSULA_HOME", Path.home() / ".clausula"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="clausula-daemon",
        description="Launch the single-owner local Clausula daemon and Capital Cockpit.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the read-only workspace in the default browser.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override CLAUSULA_HOME for this daemon run.",
    )
    args = parser.parse_args(argv)
    home = (args.home or default_home()).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)

    with DaemonLease(home / "daemon.lock"):
        store = Store(home)
        auth = LocalAuthRegistry.ephemeral_default()
        server = create_server(store, auth=auth)
        base_url = f"http://127.0.0.1:{server.server_port}"
        auth_path = write_auth_manifest(
            home / "daemon-auth.json", auth, base_url=base_url
        )
        print(f"Clausula daemon: {base_url}")
        print(f"Capital Cockpit: {base_url}/")
        print(f"Local capability credentials: {auth_path}")
        print("Workspace is anonymous read-only; capability calls require a local principal token.")
        if not args.no_browser:
            webbrowser.open(f"{base_url}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            auth_path.unlink(missing_ok=True)
            store.close()


if __name__ == "__main__":
    main()
