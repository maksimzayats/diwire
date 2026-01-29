"""Tests for scope management examples."""

from __future__ import annotations

import pytest

from tests.examples.conftest import assert_output_contains


def test_ex01_scope_basics(capsys: pytest.CaptureFixture[str]) -> None:
    """Test scope basics example."""
    from examples.ex02_scopes.ex01_scope_basics import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Scope usage with context manager:",
        "Inside scope 'request':",
        "ctx1:",
        "ctx2:",
        "Multiple independent scopes:",
        "Scope 1 context:",
        "Scope 2 context:",
        "Different instances:",
    )


def test_ex02_scoped_singleton(capsys: pytest.CaptureFixture[str]) -> None:
    """Test scoped singleton lifetime."""
    from examples.ex02_scopes.ex02_scoped_singleton import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "SCOPED behavior:",
        "Request Scope 1:",
        "session1:",
        "session2:",
        "repo.session:",
        "All same instance: True",
        "Request Scope 2:",
        "Same within scope: True",
        "Different from scope 1: True",
    )


def test_ex03_nested_scopes(capsys: pytest.CaptureFixture[str]) -> None:
    """Test nested scopes."""
    from examples.ex02_scopes.ex03_nested_scopes import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Nested scopes demonstration:",
        "Request scope - RequestContext id:",
        "Handler scope 1:",
        "HandlerContext id:",
        "Same request context: True",
        "Handler scope 2:",
        "Different handler context: True",
    )


def test_ex04_generator_factories(capsys: pytest.CaptureFixture[str]) -> None:
    """Test generator factories with scope cleanup."""
    from examples.ex02_scopes.ex04_generator_factories import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Generator factory scope behavior:",
        "opened",
        "session1:",
        "session2:",
        "Same instance: True",
        "closed",
        "Scope exited; generator cleanup should have run.",
    )
