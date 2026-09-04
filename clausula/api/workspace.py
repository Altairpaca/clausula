from __future__ import annotations

from .daemon import main as _daemon_main


def main(argv: list[str] | None = None) -> None:
    """Compatibility entry point: the workspace is now served by the single-owner daemon."""

    _daemon_main(argv)


if __name__ == "__main__":
    main()
