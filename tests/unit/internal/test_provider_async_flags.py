from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Coroutine
from contextlib import asynccontextmanager
from inspect import Parameter
from typing import Any, cast

from diwire.container import Container
from diwire.providers import ContextManagerProvider, ProviderDependency, ProviderReturnTypeExtractor


class Service:
    pass


class Dependency:
    pass


def _dependency(annotation: Any) -> ProviderDependency:
    return ProviderDependency(
        provides=annotation,
        parameter=Parameter(
            name="dependency",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=annotation,
        ),
    )


def test_return_type_extractor_detects_async_context_manager_function() -> None:
    @asynccontextmanager
    async def provide_service() -> AsyncGenerator[Service, None]:
        yield Service()

    extractor = ProviderReturnTypeExtractor()

    assert extractor.is_context_manager_async(provide_service)


def test_return_type_extractor_detects_any_async_dependency() -> None:
    extractor = ProviderReturnTypeExtractor()
    dependencies = [
        _dependency(Awaitable[Service]),
        _dependency(Coroutine[Any, Any, Service]),
    ]

    assert extractor.is_any_dependency_async(dependencies)


def test_container_sets_async_flags_for_sync_factory_with_async_dependency() -> None:
    def provide_service(dep: Awaitable[Dependency]) -> Service:
        return Service()

    container = Container()
    container.register_factory(factory=provide_service)
    spec = container._providers_registrations.get_by_type(Service)

    assert not spec.is_async
    assert spec.is_any_dependency_async


def test_container_sets_async_flags_for_async_context_manager() -> None:
    @asynccontextmanager
    async def provide_async_service() -> AsyncGenerator[Service, None]:
        yield Service()

    container = Container()
    container.register_context_manager(context_manager=provide_async_service)
    spec = container._providers_registrations.get_by_type(Service)

    assert spec.is_async
    assert not spec.is_any_dependency_async


def test_return_type_extractor_detects_coroutine_context_manager_provider() -> None:
    async def provide_service() -> Service:
        return Service()

    extractor = ProviderReturnTypeExtractor()
    typed_provider = cast("ContextManagerProvider[Any]", provide_service)

    assert extractor.is_context_manager_async(typed_provider)
