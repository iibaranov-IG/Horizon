"""Command-line boundary for the interactive Horizon setup wizard."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .wizard import main as run_wizard


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser without starting the interactive wizard."""
    return argparse.ArgumentParser(
        prog="horizon-wizard",
        description="Horizon interactive setup wizard",
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Parse standard CLI options, then start the interactive wizard."""
    parser = build_parser()
    parser.parse_args(argv)
    run_wizard()


if __name__ == "__main__":
    main()
