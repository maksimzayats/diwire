"""Tests for pytest mark-based scope override."""

from __future__ import annotations

from typing import Annotated

import pytest

from diwire.container import Container
from diwire.types import Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class Service:
    """Service used for marker scope tests."""


@pytest.fixture()
def diwire_container() -> Container:
    container = Container(autoregister=False)
    container.register(Service, lifetime=Lifetime.SCOPED, scope="marker_scope")
    return container


@pytest.fixture()
def diwire_scope() -> str:
    return "default_scope"


@pytest.mark.diwire_scope("marker_scope")
def test_marker_scope_overrides_default(service: Annotated[Service, Injected()]) -> None:
    assert isinstance(service, Service)


@pytest.mark.diwire_scope(scope="marker_scope")
def test_marker_scope_kwarg(service: Annotated[Service, Injected()]) -> None:
    assert isinstance(service, Service)
