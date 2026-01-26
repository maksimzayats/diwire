"""Shared fixtures for example tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

# Add examples to Python path
EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"
sys.path.insert(0, str(EXAMPLES_DIR.parent))


def assert_output_contains(output: str, *expected: str) -> None:
    """Assert that output contains all expected substrings."""
    for text in expected:
        assert text in output, f"Missing: {text!r}\nActual:\n{output}"


@pytest.fixture()
def reset_counter() -> Callable[[], None]:
    """Factory fixture to reset class counters between tests."""

    def _reset() -> None:
        from examples.ex03_function_injection.ex02_injected_wrapper import Counter

        Counter._counter = 0

    return _reset


@pytest.fixture()
def reset_request_context_counter() -> Callable[[], None]:
    """Reset RequestContext counter for async scoped injection tests."""

    def _reset() -> None:
        from examples.ex06_async.ex04_async_scoped_injection import RequestContext

        RequestContext._counter = 0

    return _reset


@pytest.fixture()
def reset_database_session_counter() -> Callable[[], None]:
    """Reset DatabaseSession counter for fastapi_style tests."""

    def _reset() -> None:
        from examples.ex06_async.ex07_fastapi_style import DatabaseSession

        DatabaseSession._counter = 0

    return _reset
