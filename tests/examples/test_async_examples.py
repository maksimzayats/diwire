"""Tests for async diwire examples."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.examples.conftest import assert_output_contains

if TYPE_CHECKING:
    from collections.abc import Callable


async def test_ex01_basic_async_factory(capsys: pytest.CaptureFixture[str]) -> None:
    """Test basic async factory example."""
    from examples.ex06_async.ex01_basic_async_factory import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Database connected: True",
        "Query results:",
        "Same instance: True",
    )


async def test_ex02_async_generator_cleanup(capsys: pytest.CaptureFixture[str]) -> None:
    """Test async generator cleanup example."""
    from examples.ex06_async.ex02_async_generator_cleanup import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Created session session-123",
        "Got session: session-123",
        "Same session: True",
        "Closing session session-123",
        "Session closed: True",
    )


async def test_ex03_async_injected_functions(capsys: pytest.CaptureFixture[str]) -> None:
    """Test async function injection with Injected."""
    from examples.ex06_async.ex03_async_injected_functions import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Resolved handler type:",
        "[LOG] Fetching user 42",
        "[LOG] Found user: User 42",
        "Sent email to",
        "(Injected parameters are hidden from the signature)",
    )


async def test_ex04_async_scoped_injection(
    capsys: pytest.CaptureFixture[str],
    reset_request_context_counter: Callable[[], None],
) -> None:
    """Test async scoped function injection."""
    reset_request_context_counter()

    from examples.ex06_async.ex04_async_scoped_injection import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Handler type:",
        "Created req-",
        "Created transaction for req-",
        "Processing request req-",
        "Different request IDs:",
    )


async def test_ex05_mixed_and_parallel(capsys: pytest.CaptureFixture[str]) -> None:
    """Test mixed sync/async dependencies and parallel resolution."""
    from examples.ex06_async.ex05_mixed_and_parallel import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Resolving ApplicationService with 3 async dependencies",
        "Resolution completed in",
        "db_pool_size': 10",
        "cache_connected': True",
        "api_authenticated': True",
        "Dependencies were resolved in PARALLEL",
        "Same instance: True",
    )


async def test_ex06_error_handling(capsys: pytest.CaptureFixture[str]) -> None:
    """Test async error handling patterns."""
    from examples.ex06_async.ex06_error_handling import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "DIWireAsyncDependencyInSyncContextError",
        "DIWireAsyncGeneratorFactoryWithoutScopeError",
        "Correct Usage",
        "Cleanup runs automatically on scope exit",
    )


async def test_ex07_fastapi_style(
    capsys: pytest.CaptureFixture[str],
    reset_database_session_counter: Callable[[], None],
) -> None:
    """Test FastAPI-style async DI pattern."""
    reset_database_session_counter()

    from examples.ex06_async.ex07_fastapi_style import main

    await main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "FastAPI-Style Async DI Demo",
        "Processing concurrent requests",
        "[Session",
        "Results",
    )
