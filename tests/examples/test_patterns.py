"""Tests for common DI pattern examples."""

from __future__ import annotations

import pytest

from tests.examples.conftest import assert_output_contains


def test_ex01_request_handler(capsys: pytest.CaptureFixture[str]) -> None:
    """Test HTTP request handler pattern."""
    from examples.ex05_patterns.ex01_request_handler import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Simulating HTTP requests:",
        "Request 1 (valid token):",
        "user_id': 42",
        "Request 2 (invalid token):",
        "error': 'Not authenticated'",
        "Request 3 (valid token, different user):",
        "user_id': 99",
    )


def test_ex02_repository(capsys: pytest.CaptureFixture[str]) -> None:
    """Test repository pattern with scoped session."""
    from examples.ex05_patterns.ex02_repository import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Repository pattern with scoped session:",
        "Unit of Work 1:",
        "Staged: INSERT User",
        "Staged: INSERT Order",
        "Committing",
        "Unit of Work 2:",
        "Manual scope management:",
        "Same session: True",
    )


def test_ex03_class_methods(capsys: pytest.CaptureFixture[str]) -> None:
    """Test class method decoration pattern."""
    from examples.ex05_patterns.ex03_class_methods import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Instance Method Decoration Example",
        "Calling list_users():",
        "[INFO] /v1/api/users - Fetching all users",
        "Result:",
        "Calling get_user_cached('1') - first call (cache miss):",
        "Cache miss, querying DB",
        "Calling get_user_cached('1') - second call (cache hit):",
        "Cache hit",
        "controller.prefix = '/v1/api'",
    )


def test_ex04_interface_registration(capsys: pytest.CaptureFixture[str]) -> None:
    """Test interface registration pattern."""
    from examples.ex05_patterns.ex04_interface_registration import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "[LOG] Application starting...",
        "[LOG] Creating user: john_doe",
        "[LOG] Saving data:",
        "[LOG] Sending email to john@example.com:",
        "Stored data:",
        "user:john_doe",
    )
