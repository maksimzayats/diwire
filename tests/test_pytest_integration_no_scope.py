"""Tests for pytest integration with scope disabled."""

from __future__ import annotations

from typing import Annotated, Any, cast

import pytest

from diwire.container import Container
from diwire.integrations.pytest_plugin import _normalize_scope, _resolve_scope_from_config
from diwire.types import Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class Service:
    """Simple service for no-scope tests."""


@pytest.fixture()
def diwire_scope() -> str | None:
    return None


@pytest.fixture()
def diwire_container() -> Container:
    container = Container()
    container.register(Service, lifetime=Lifetime.SINGLETON)
    return container


def test_injection_without_scope(service: Annotated[Service, Injected()]) -> None:
    assert isinstance(service, Service)


def test_normalize_scope_none() -> None:
    assert _normalize_scope(None) is None


def test_normalize_scope_empty() -> None:
    assert _normalize_scope("   ") is None


def test_diwire_scope_uses_ini_when_option_missing() -> None:
    class DummyConfig:
        def getoption(self, name: str) -> None:
            return None

        def getini(self, name: str) -> str:
            return " test_function "

    assert _resolve_scope_from_config(cast("Any", DummyConfig())) == "test_function"


def test_diwire_scope_prefers_option_value() -> None:
    class DummyConfig:
        def getoption(self, name: str) -> str:
            return "custom_scope"

        def getini(self, name: str) -> str:  # pragma: no cover - should not be used
            return "ignored"

    assert _resolve_scope_from_config(cast("Any", DummyConfig())) == "custom_scope"
