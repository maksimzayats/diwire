from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "diwire").is_dir():
            return candidate
    msg = f"Could not locate repository root from {start}"
    raise AssertionError(msg)


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
RUNNER_JS = (
    REPO_ROOT
    / "docs"
    / "sphinx-pyodide-runner"
    / "sphinx_pyodide_runner"
    / "_static"
    / "pyodide-runner.js"
)
AUTO_OPEN_SCOPE_REUSE_EXAMPLE = (
    REPO_ROOT / "examples" / "ex_06_function_injection" / "05_auto_open_scope_reuse.py"
)
SINGLETON_CLEANUP_EXAMPLE = (
    REPO_ROOT / "examples" / "ex_04_scopes_and_cleanup" / "04_singleton_cleanup.py"
)
_RUNNER_PYTHON_RE = re.compile(
    r"const result = await pyodide\.runPythonAsync\(`\n(?P<code>.*?)\n`\);",
    re.DOTALL,
)


def _extract_runner_python() -> str:
    text = RUNNER_JS.read_text(encoding="utf-8")
    match = _RUNNER_PYTHON_RE.search(text)
    if match is None:
        msg = "Could not find runner Python code in pyodide-runner.js"
        raise AssertionError(msg)
    return match.group("code")


def _eval_last_expression(source: str, globals_dict: dict[str, Any]) -> Any:
    module = ast.parse(source)
    if not module.body or not isinstance(module.body[-1], ast.Expr):
        msg = "Runner Python code must end with the result expression."
        raise AssertionError(msg)

    module.body[-1] = ast.Assign(
        targets=[ast.Name(id="__runner_result__", ctx=ast.Store())],
        value=module.body[-1].value,
    )
    ast.fix_missing_locations(module)
    exec(compile(module, "<test-pyodide-runner>", "exec"), globals_dict)  # noqa: S102
    return globals_dict["__runner_result__"]


def test_pyodide_runner_caches_dynamic_source_for_inspection() -> None:
    code = """
import inspect


def main() -> None:
    def provider():
        try:
            yield 1
        finally:
            pass

    print(f"source_has_finally={'finally' in inspect.getsource(provider)}")


if __name__ == "__main__":
    main()
""".strip()

    stdout, stderr = _eval_last_expression(
        _extract_runner_python(),
        {"__RUN_CODE__": code},
    )

    assert stdout == "source_has_finally=True\n"
    assert stderr == ""


def test_pyodide_runner_executes_auto_open_scope_reuse_example() -> None:
    stdout, stderr = _eval_last_expression(
        _extract_runner_python(),
        {"__RUN_CODE__": AUTO_OPEN_SCOPE_REUSE_EXAMPLE.read_text(encoding="utf-8")},
    )

    assert stdout.splitlines() == [
        "target_scope_reused=True",
        "cleanup_after_outer_scope=True",
        "deeper_scope_contextvar_reused=22",
    ]
    assert stderr == ""


def test_pyodide_runner_executes_singleton_cleanup_example() -> None:
    stdout, stderr = _eval_last_expression(
        _extract_runner_python(),
        {"__RUN_CODE__": SINGLETON_CLEANUP_EXAMPLE.read_text(encoding="utf-8")},
    )

    assert stdout == "singleton_cleanup_on_close=True\n"
    assert stderr == ""
