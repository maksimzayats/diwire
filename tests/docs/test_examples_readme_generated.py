from __future__ import annotations

import difflib
from pathlib import Path

from tools.generate_examples_readme import build_updated_readme_text


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
EXAMPLES_ROOT = REPO_ROOT / "examples"
README_PATH = EXAMPLES_ROOT / "README.md"


def test_examples_readme_is_in_sync_with_generated_region() -> None:
    current_text = README_PATH.read_text(encoding="utf-8")
    expected_text = build_updated_readme_text(readme_text=current_text, examples_root=EXAMPLES_ROOT)
    if current_text == expected_text:
        return

    diff = "\n".join(
        difflib.unified_diff(
            current_text.splitlines(),
            expected_text.splitlines(),
            fromfile="examples/README.md (current)",
            tofile="examples/README.md (generated)",
            lineterm="",
        ),
    )
    msg = (
        "examples/README.md is out of sync with example files.\n"
        "Run one of:\n"
        "  uv run python -m tools.generate_examples_readme\n"
        "  make examples-readme\n\n"
        f"diff:\n{diff or '<no diff>'}"
    )
    raise AssertionError(msg)
