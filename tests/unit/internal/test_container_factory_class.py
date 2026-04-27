from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest

from diwire import Container, Injected, Lifetime
from diwire.exceptions import DIWireInvalidRegistrationError


@dataclass(frozen=True)
class _Settings:
    prefix: str


@dataclass(frozen=True)
class _Client:
    name: str


@dataclass(kw_only=True)
class _ClientFactory:
    settings: Injected[_Settings]

    def __call__(self) -> _Client:
        return _Client(name=f"{self.settings.prefix}-client")


@dataclass(kw_only=True)
class _AsyncClientFactory:
    settings: Injected[_Settings]

    async def __call__(self) -> _Client:
        return _Client(name=f"{self.settings.prefix}-async-client")


@dataclass(kw_only=True)
class _ExplicitClientFactory:
    settings: _Settings

    def __call__(self) -> Any:
        return _Client(name=f"{self.settings.prefix}-explicit-client")


class _NotFactory:
    pass


def test_add_factory_class_infers_provides_and_constructor_dependencies() -> None:
    container = Container()
    container.add_instance(_Settings(prefix="main"))

    container.add_factory_class(_ClientFactory)

    resolved = container.resolve(_Client)

    assert resolved == _Client(name="main-client")
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.factory is not None
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == ["settings"]


async def test_add_factory_class_supports_async_call_method() -> None:
    container = Container()
    container.add_instance(_Settings(prefix="main"))

    container.add_factory_class(_AsyncClientFactory)

    resolved = await container.aresolve(_Client)

    assert resolved == _Client(name="main-async-client")
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.is_async


def test_add_factory_class_supports_explicit_provides_for_untyped_call_method() -> None:
    container = Container(default_lifetime=Lifetime.TRANSIENT)
    container.add_instance(_Settings(prefix="main"))

    container.add_factory_class(_ExplicitClientFactory, provides=_Client)

    first = container.resolve(_Client)
    second = container.resolve(_Client)

    assert first == _Client(name="main-explicit-client")
    assert second == _Client(name="main-explicit-client")
    assert first is not second


@pytest.mark.parametrize(
    ("factory_class", "match"),
    [
        (
            cast("Any", object()),
            "add_factory_class\\(\\) parameter 'factory_class' must be a class",
        ),
        (
            _NotFactory,
            "add_factory_class\\(\\) parameter 'factory_class' must define an instance __call__",
        ),
    ],
)
def test_add_factory_class_rejects_invalid_factory_class(
    factory_class: type[Any],
    match: str,
) -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        container.add_factory_class(factory_class)
