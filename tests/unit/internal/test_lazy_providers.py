from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

import pytest

from diwire import AsyncProvider, Container, Injected, Lifetime, Provider, Scope
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireInvalidProviderSpecError,
)


class _CycleB:
    def __init__(self, a: _CycleA) -> None:
        self.a = a


class _CycleA:
    def __init__(self, b_provider: Provider[_CycleB]) -> None:
        self._b_provider = b_provider

    def get_b(self) -> _CycleB:
        return self._b_provider()


class _DirectCycleA:
    def __init__(self, b: _DirectCycleB) -> None:
        self.b = b


class _DirectCycleB:
    def __init__(self, a: _DirectCycleA) -> None:
        self.a = a


class _RequestDependency:
    pass


class _RequestProviderConsumer:
    def __init__(self, dependency_provider: Provider[_RequestDependency]) -> None:
        self._dependency_provider = dependency_provider

    def get(self) -> _RequestDependency:
        return self._dependency_provider()


class _ScopedActionDependency:
    pass


class _RequestScopedProviderConsumer:
    def __init__(self, dependency_provider: Provider[_ScopedActionDependency]) -> None:
        self._dependency_provider = dependency_provider


class _VarArgDependency:
    pass


class _VarArgProviderConsumer:
    pass


def _build_vararg_provider_consumer(
    *providers: Provider[_VarArgDependency],
) -> _VarArgProviderConsumer:
    return _VarArgProviderConsumer()


class _VarKwProviderConsumer:
    pass


def _build_varkw_provider_consumer(
    **providers: Provider[_VarArgDependency],
) -> _VarKwProviderConsumer:
    return _VarKwProviderConsumer()


class _AsyncDependency:
    pass


class _AsyncConsumer:
    def __init__(self, dependency_provider: AsyncProvider[_AsyncDependency]) -> None:
        self._dependency_provider = dependency_provider

    async def get(self) -> _AsyncDependency:
        return await self._dependency_provider()


class _SyncProviderForAsyncDependency:
    def __init__(self, dependency_provider: Provider[_AsyncDependency]) -> None:
        self._dependency_provider = dependency_provider

    def get(self) -> _AsyncDependency:
        return self._dependency_provider()


class _InjectedConsumerDependency:
    pass


class _AutoregDependency:
    pass


class _AutoregConsumer:
    def __init__(self, dep_provider: Provider[_AutoregDependency]) -> None:
        self.dep_provider = dep_provider


@pytest.mark.asyncio
async def test_cycle_with_provider_breaks_codegen_cycle_and_resolves() -> None:
    container = Container()
    container.add_concrete(_CycleA)
    container.add_concrete(_CycleB)

    resolved = container.resolve(_CycleA)
    resolved_b = resolved.get_b()

    assert isinstance(resolved_b, _CycleB)
    assert resolved_b.a is resolved


def test_unbroken_direct_cycle_still_raises() -> None:
    container = Container()
    container.add_concrete(_DirectCycleA)
    container.add_concrete(_DirectCycleB)

    with pytest.raises(DIWireInvalidProviderSpecError, match="Circular dependency detected"):
        container.resolve(_DirectCycleA)


def test_provider_preserves_scoped_lifetime_within_same_scope() -> None:
    container = Container()
    container.add_concrete(
        _RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _RequestProviderConsumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        consumer = request_scope.resolve(_RequestProviderConsumer)
        first = consumer.get()
        second = consumer.get()

    assert first is second


def test_provider_preserves_transient_lifetime_within_same_scope() -> None:
    container = Container()
    container.add_concrete(
        _RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_concrete(
        _RequestProviderConsumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        consumer = request_scope.resolve(_RequestProviderConsumer)
        first = consumer.get()
        second = consumer.get()

    assert first is not second


@pytest.mark.asyncio
async def test_async_provider_returns_awaitable_and_resolves_dependency() -> None:
    async def _build_dependency() -> _AsyncDependency:
        return _AsyncDependency()

    container = Container()
    container.add_factory(_build_dependency, provides=_AsyncDependency)
    container.add_concrete(_AsyncConsumer)

    consumer = container.resolve(_AsyncConsumer)
    dependency = await consumer.get()

    assert isinstance(dependency, _AsyncDependency)


def test_sync_provider_to_async_chain_raises_on_call() -> None:
    async def _build_dependency() -> _AsyncDependency:
        return _AsyncDependency()

    container = Container()
    container.add_factory(_build_dependency, provides=_AsyncDependency)
    container.add_concrete(_SyncProviderForAsyncDependency)

    consumer = container.resolve(_SyncProviderForAsyncDependency)

    with pytest.raises(
        DIWireAsyncDependencyInSyncContextError,
        match="requires asynchronous resolution",
    ):
        _ = consumer.get()


@pytest.mark.asyncio
async def test_direct_resolve_provider_and_async_provider_dependency_keys() -> None:
    container = Container()
    container.add_concrete(_InjectedConsumerDependency)
    resolver = container.compile()

    provider = resolver.resolve(Provider[_InjectedConsumerDependency])
    async_provider = resolver.resolve(AsyncProvider[_InjectedConsumerDependency])
    provider_from_async = await resolver.aresolve(Provider[_InjectedConsumerDependency])
    async_provider_from_async = await resolver.aresolve(AsyncProvider[_InjectedConsumerDependency])

    assert isinstance(provider(), _InjectedConsumerDependency)
    assert isinstance(await async_provider(), _InjectedConsumerDependency)
    assert isinstance(provider_from_async(), _InjectedConsumerDependency)
    assert isinstance(await async_provider_from_async(), _InjectedConsumerDependency)


@pytest.mark.asyncio
async def test_injected_wrapper_supports_provider_and_async_provider() -> None:
    container = Container()
    container.add_concrete(_InjectedConsumerDependency)

    @container.inject
    def _sync_handler(
        dependency_provider: Injected[Provider[_InjectedConsumerDependency]],
    ) -> _InjectedConsumerDependency:
        return dependency_provider()

    @container.inject
    async def _async_handler(
        dependency_provider: Injected[AsyncProvider[_InjectedConsumerDependency]],
    ) -> _InjectedConsumerDependency:
        return await dependency_provider()

    sync_handler = cast("Any", _sync_handler)
    async_handler = cast("Any", _async_handler)

    assert isinstance(sync_handler(), _InjectedConsumerDependency)
    assert isinstance(await async_handler(), _InjectedConsumerDependency)


T = TypeVar("T")


class _OpenProviderService(Generic[T]):
    pass


@dataclass
class _OpenProviderServiceImpl(_OpenProviderService[T]):
    type_arg: type[T]


def _build_open_provider_service(type_arg: type[T]) -> _OpenProviderService[T]:
    return _OpenProviderServiceImpl(type_arg=type_arg)


def test_provider_direct_resolve_supports_open_generic_dependencies() -> None:
    container = Container()
    container.add_factory(_build_open_provider_service, provides=_OpenProviderService)
    resolver = container.compile()

    provider = resolver.resolve(Provider[_OpenProviderService[int]])
    resolved = provider()

    assert isinstance(resolved, _OpenProviderServiceImpl)
    assert resolved.type_arg is int


def test_autoregistration_unwraps_provider_dependency() -> None:
    container = Container()
    container.add_concrete(_AutoregConsumer)

    assert container._providers_registrations.find_by_type(_AutoregDependency) is not None


def test_provider_rejects_deeper_scoped_dependency_during_planning() -> None:
    container = Container()
    container.add_concrete(
        _ScopedActionDependency,
        scope=Scope.ACTION,
        lifetime=Lifetime.SCOPED,
    )
    container.add_concrete(
        _RequestScopedProviderConsumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(
        DIWireInvalidProviderSpecError,
        match="cannot bind deeper dependency",
    ):
        container.compile()


@pytest.mark.parametrize(
    "factory",
    [_build_vararg_provider_consumer, _build_varkw_provider_consumer],
)
def test_provider_rejects_star_parameter_shapes(factory: object) -> None:
    container = Container()
    container.add_concrete(_VarArgDependency)
    container.add_factory(
        cast("Any", factory),
        provides=(
            _VarArgProviderConsumer
            if factory is _build_vararg_provider_consumer
            else _VarKwProviderConsumer
        ),
    )

    with pytest.raises(
        DIWireInvalidProviderSpecError,
        match=r"star parameters \(\*args/\*\*kwargs\)",
    ):
        container.compile()
