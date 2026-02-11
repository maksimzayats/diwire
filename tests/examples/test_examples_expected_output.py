from __future__ import annotations

import ast
import difflib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
EXAMPLES_ROOT = REPO_ROOT / "examples"
SRC_ROOT = REPO_ROOT / "src"


@dataclass(frozen=True, slots=True)
class ExampleCase:
    path: Path
    expected_lines: list[str]


def _iter_example_paths() -> list[Path]:
    paths: list[Path] = []
    for topic_dir in sorted(path for path in EXAMPLES_ROOT.glob("ex_*") if path.is_dir()):
        topic_files = sorted(topic_dir.glob("01_*.py"))
        if len(topic_files) != 1:
            msg = (
                f"{topic_dir}: expected exactly one main topic file matching "
                "'01_*.py' (found {len(topic_files)})."
            )
            raise AssertionError(msg)
        paths.append(topic_files[0])
    return paths


def _extract_expected_lines(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path))
    source_lines = source.splitlines()

    print_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    print_calls.sort(key=lambda node: (node.lineno, node.col_offset))

    expected_lines: list[str] = []
    for print_call in print_calls:
        end_lineno = print_call.end_lineno
        if end_lineno is None:
            msg = f"{path}: print() node is missing end line information."
            raise AssertionError(msg)

        closing_line = source_lines[end_lineno - 1]
        if "# =>" not in closing_line:
            msg = (
                f"{path}:{end_lineno}: print() closing line must include '# =>' "
                "with exact expected output."
            )
            raise AssertionError(msg)

        expected_lines.append(closing_line.split("# =>", maxsplit=1)[1].strip())

    return expected_lines


def _build_cases() -> list[object]:
    return [
        pytest.param(
            ExampleCase(path=path, expected_lines=_extract_expected_lines(path)),
            id=str(path.relative_to(REPO_ROOT)),
        )
        for path in _iter_example_paths()
    ]


@pytest.mark.parametrize("case", _build_cases())
def test_examples_stdout_matches_inline_expectations(case: ExampleCase) -> None:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SRC_ROOT)
        if not existing_pythonpath
        else os.pathsep.join((str(SRC_ROOT), existing_pythonpath))
    )

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(case.path)],
        cwd=case.path.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    actual_lines = completed.stdout.splitlines()

    if completed.returncode != 0 or completed.stderr != "" or actual_lines != case.expected_lines:
        diff = "\n".join(
            difflib.unified_diff(
                case.expected_lines,
                actual_lines,
                fromfile="expected",
                tofile="actual",
                lineterm="",
            ),
        )
        expected_block = "\n".join(case.expected_lines) or "<no stdout>"
        actual_block = "\n".join(actual_lines) or "<no stdout>"

        msg = (
            f"Example execution mismatch for {case.path}\n"
            f"returncode={completed.returncode}\n"
            f"stderr:\n{completed.stderr or '<empty>'}\n\n"
            f"expected stdout lines:\n{expected_block}\n\n"
            f"actual stdout lines:\n{actual_block}\n\n"
            f"diff:\n{diff or '<no diff>'}"
        )
        raise AssertionError(msg)
