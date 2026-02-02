"""Tests for pytest integration with custom scope fixture."""

from __future__ import annotations

import pytest

from diwire.container import Container
from diwire.types import Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class ScopedService:
    """Scoped service for custom scope."""


@pytest.fixture()
def diwire_scope() -> str:
    return "custom_scope"


@pytest.fixture()
def diwire_container() -> Container:
    container = Container()
    container.register(ScopedService, lifetime=Lifetime.SCOPED, scope="custom_scope")
    return container


def test_custom_scope_is_used(
    first: Injected[ScopedService],
    second: Injected[ScopedService],
) -> None:
    assert first is second
