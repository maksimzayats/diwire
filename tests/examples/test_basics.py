"""Tests for basic diwire examples."""

from __future__ import annotations

import pytest

from tests.examples.conftest import assert_output_contains


def test_ex01_registration(capsys: pytest.CaptureFixture[str]) -> None:
    """Test registration example demonstrates all registration methods."""
    from examples.ex01_basics.ex01_registration import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "[LOG] Hello from registered class!",
        "Database: localhost:5432",
        "Cache data: {'key': 'value'}",
        "Same instance: True",
    )


def test_ex02_lifetimes(capsys: pytest.CaptureFixture[str]) -> None:
    """Test lifetimes example shows TRANSIENT vs SINGLETON behavior."""
    from examples.ex01_basics.ex02_lifetimes import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "TRANSIENT instances:",
        "All different: True",
        "SINGLETON instances:",
        "All same: True",
    )


def test_ex03_constructor_injection(capsys: pytest.CaptureFixture[str]) -> None:
    """Test constructor injection resolves entire dependency chain."""
    from examples.ex01_basics.ex03_constructor_injection import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "postgresql://prod/app",
        "SELECT * FROM users WHERE id = 42",
        "Dependency chain resolved:",
    )
