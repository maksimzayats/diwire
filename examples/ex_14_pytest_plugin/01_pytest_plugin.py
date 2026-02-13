"""Pytest plugin integration smoke test.

Runs ``pytest -q test_demo.py`` in this folder to validate
``diwire.integrations.pytest_plugin`` with ``Injected[T]`` test parameters.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    example_dir = Path(__file__).resolve().parent
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "test_demo.py"],
        cwd=example_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"exit_code={completed.returncode}")  # => exit_code=0


if __name__ == "__main__":
    main()
