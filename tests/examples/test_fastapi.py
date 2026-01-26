"""Tests for FastAPI integration examples."""

from __future__ import annotations

import pytest


def test_ex01_basic(capsys: pytest.CaptureFixture[str]) -> None:
    """Test basic FastAPI integration."""
    from fastapi.testclient import TestClient

    from examples.ex08_fastapi.ex01_basic import app

    client = TestClient(app)

    response = client.get("/greet")
    assert response.status_code == 200

    data = response.json()
    assert "message" in data
    assert "Hello from Service!" in data["message"]
    assert "request_id" in data

    # Verify cleanup ran
    captured = capsys.readouterr()
    assert "Closing service" in captured.out


def test_ex02_decorator(capsys: pytest.CaptureFixture[str]) -> None:
    """Test decorator-based FastAPI integration."""
    from fastapi.testclient import TestClient

    from examples.ex08_fastapi.ex02_decorator import app

    client = TestClient(app)

    response = client.get("/greet?name=TestUser")
    assert response.status_code == 200

    data = response.json()
    assert "message" in data
    assert "TestUser" in data["message"]
    assert "Hello" in data["message"]

    # Verify cleanup ran
    captured = capsys.readouterr()
    assert "Closing service" in captured.out


def test_ex03_context_container_decorator(capsys: pytest.CaptureFixture[str]) -> None:
    """Test context container decorator integration."""
    from fastapi.testclient import TestClient

    from diwire.container_context import _current_container
    from examples.ex08_fastapi.ex03_context_container_decorator import app, setup_container

    setup_container()
    try:
        client = TestClient(app)

        # Test first endpoint
        response = client.get("/greet?name=Alice")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "Alice" in data["message"]

        # Test second endpoint (Handler class method)
        response2 = client.get("/greet/v2?name=Bob")
        assert response2.status_code == 200
        assert "request_id" in response2.json()

        # Verify cleanup ran
        captured = capsys.readouterr()
        assert "Closing service" in captured.out
    finally:
        # Reset container context to avoid polluting other tests
        _current_container.set(None)
