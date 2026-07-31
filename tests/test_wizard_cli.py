"""Regression tests for the setup wizard command-line boundary."""

from __future__ import annotations

import subprocess
import sys


def test_wizard_help_is_non_interactive() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.setup.wizard_cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "setup wizard" in result.stdout.lower()
    assert "traceback" not in result.stderr.lower()
