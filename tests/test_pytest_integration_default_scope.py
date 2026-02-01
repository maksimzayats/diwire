"""Tests for pytest integration with default scope."""

from __future__ import annotations

from typing import Annotated

import pytest

from diwire.container import Container
from diwire.types import Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class Service:
    """Simple service."""


class ScopedService:
    """Scoped service for default scope."""


@pytest.fixture()
def diwire_container() -> Container:
    container = Container()
    container.register(Service, lifetime=Lifetime.SINGLETON)
    container.register(ScopedService, lifetime=Lifetime.SCOPED, scope="test_function")
    return container


@pytest.fixture()
def value() -> int:
    return 42


def test_injected_params_are_resolved(
    value: int,
    service: Annotated[Service, Injected()],
) -> None:
    assert value == 42
    assert isinstance(service, Service)


def test_default_scope_is_applied(
    first: Annotated[ScopedService, Injected()],
    second: Annotated[ScopedService, Injected()],
) -> None:
    assert first is second


def test_no_injection_needed(value: int) -> None:
    assert value == 42


@pytest.mark.asyncio
async def test_async_injection(service: Annotated[Service, Injected()]) -> None:
    assert isinstance(service, Service)
