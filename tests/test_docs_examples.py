from __future__ import annotations

import contextlib
import io
import sys
import types
from pathlib import Path

from tests.docs_examples import iter_rst_code_blocks


def _run_example_code(*, code: str, filename: str) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    module = types.ModuleType("__main__")
    module.__dict__["__name__"] = "__main__"
    module.__dict__["__package__"] = None
    old_main = sys.modules.get("__main__")
    sys.modules["__main__"] = module

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(code, filename, "exec"), module.__dict__)  # noqa: S102
    finally:
        if old_main is None:
            del sys.modules["__main__"]
        else:
            sys.modules["__main__"] = old_main

    # Ensure we don't leak a global container between examples.
    with contextlib.suppress(ImportError):
        from diwire.container_context import _current_container

        _current_container.set(None)


def test_docs_runnable_examples_execute() -> None:
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    blocks = iter_rst_code_blocks(docs_dir=docs_dir)

    example_blocks = [b for b in blocks if "diwire-example" in b.classes]
    assert example_blocks, (
        "No docs examples found (expected code blocks with :class: diwire-example)"
    )

    failures: list[str] = []
    for block in example_blocks:
        filename = f"{block.path}:{block.lineno}"
        try:
            _run_example_code(code=block.code, filename=filename)
        except Exception as exc:
            failures.append(f"{filename}: {type(exc).__name__}: {exc}")

    if failures:
        formatted = "\n".join(failures)
        msg = "Some docs examples failed to execute:\n" + formatted
        raise AssertionError(msg)
