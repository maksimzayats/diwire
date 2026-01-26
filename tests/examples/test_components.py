"""Tests for components examples."""

from __future__ import annotations

import pytest

from tests.examples.conftest import assert_output_contains


def test_ex01_named_components(capsys: pytest.CaptureFixture[str]) -> None:
    """Test named components for multiple implementations."""
    from examples.ex04_components.ex01_named_components import main

    main()
    captured = capsys.readouterr()

    assert_output_contains(
        captured.out,
        "Direct resolution by ServiceKey:",
        "[Postgres@primary.postgres.example.com]",
        "[MySQL@replica.mysql.example.com]",
        "Resolution by Annotated type:",
        "Repository with injected components:",
        "Write:",
        "Read:",
    )
