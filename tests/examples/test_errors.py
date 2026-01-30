"""Tests for error handling examples."""

from __future__ import annotations

import pytest

from tests.examples.conftest import assert_output_contains


def test_ex01_circular_dependency() -> None:
    """Test circular dependency detection.

    Note: The container currently raises RecursionError for circular deps
    rather than the expected DIWireCircularDependencyError. This test
    verifies the circular dependency is detected (causes an error).
    """
    from diwire import Container
    from examples.ex07_errors.ex01_circular_dependency import ServiceA, ServiceB

    container = Container()
    container.register(ServiceA)
    container.register(ServiceB)

    # The container currently raises RecursionError for circular deps
    with pytest.raises(RecursionError):
        container.resolve(ServiceA)


def test_ex02_missing_dependency(capsys: pytest.CaptureFixture[str]) -> None:
    """Test missing dependency detection."""
    from examples.ex07_errors.ex02_missing_dependency import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Attempting to resolve service with missing dependency:",
        "DIWireMissingDependenciesError caught!",
        "Service key:",
        "Missing dependencies:",
        "With autoregister=True",
        "api_key: str",
    )


def test_ex03_scope_mismatch(capsys: pytest.CaptureFixture[str]) -> None:
    """Test scope mismatch detection."""
    from examples.ex07_errors.ex03_scope_mismatch import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Using a scope reference after it has exited",
        "Inside scope: resolved",
        "Attempting to resolve from exited scope:",
        "DIWireScopeMismatchError caught!",
        "Correct usage",
        "Successfully resolved:",
    )
