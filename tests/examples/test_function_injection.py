"""Tests for function injection examples."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.examples.conftest import assert_output_contains

if TYPE_CHECKING:
    from collections.abc import Callable


def test_ex01_injected(capsys: pytest.CaptureFixture[str]) -> None:
    """Test Injected marker for function injection."""
    from examples.ex03_function_injection.ex01_injected import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Resolved function type:",
        "[LOG] Sending welcome email to Alice",
        "Email sent to alice@example.com: Welcome, Alice!",
        "[LOG] Sending welcome email to Bob",
        "Email sent to bob@example.com: Welcome, Bob!",
    )


def test_ex02_injected_wrapper(
    capsys: pytest.CaptureFixture[str],
    reset_counter: Callable[[], None],
) -> None:
    """Test Injected wrapper behavior."""
    reset_counter()

    from examples.ex03_function_injection.ex02_injected_wrapper import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Fresh resolution on each call:",
        "Processing item 1 with counter instance #1",
        "Processing item 2 with counter instance #2",
        "Processing item 3 with counter instance #3",
        "Original signature:",
        "Injected signature:",
        "counter' parameter is removed from signature",
        "Overriding injected dependency:",
        "Processing item 100 with counter instance #999",
    )


def test_ex03_scoped_injected(capsys: pytest.CaptureFixture[str]) -> None:
    """Test ScopedInjected for per-call scopes."""
    from examples.ex03_function_injection.ex03_scoped_injected import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Handler type:",
        "ScopedInjected",
        "Each call creates a new scope:",
        "Request 1:",
        "Request 2:",
        "Request 3:",
        # Session IDs match within request
        "session:",
    )
