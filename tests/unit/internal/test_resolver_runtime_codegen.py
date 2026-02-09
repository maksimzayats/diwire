from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncGenerator, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import TracebackType
from typing import Any, cast

import pytest

from diwire.container import Container
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireScopeMismatchError,
)
from diwire.providers import Lifetime, ProviderDependency, ProviderSpec
from diwire.resolvers.templates.renderer import ResolversTemplateRenderer
from diwire.scope import Scope


class _SingletonService:
    pass


class _TransientService:
    pass


class _RequestService:
    pass


class _SessionService:
    pass


class _Resource:
    pass


class _DependsOnResource:
    def __init__(self, resource: _Resource) -> None:
        self.resource = resource


class _PosOnlyDependency:
    pass


class _PosOnlyService:
    def __init__(self, dependency: _PosOnlyDependency) -> None:
        self.dependency = dependency


class _VarArgsService:
    def __init__(self, values: tuple[int, ...]) -> None:
        self.values = values


class _KwArgsService:
    def __init__(self, options: dict[str, int]) -> None:
        self.options = options


class _SessionAsyncService:
    pass


def test_sync_singleton_uses_lambda_method_replacement_cache() -> None:
    calls = 0

    def build_service() -> _SingletonService:
        nonlocal calls
        calls += 1
        return _SingletonService()

    container = Container()
    container.register_factory(
        _SingletonService,
        factory=build_service,
        lifetime=Lifetime.SINGLETON,
    )

    first = container.resolve(_SingletonService)
    second = container.resolve(_SingletonService)

    assert first is second
    assert calls == 1

    root_resolver = container._root_resolver
    assert root_resolver is not None
    slot = container._providers_registrations.get_by_type(_SingletonService).slot
    cached_method = getattr(root_resolver, f"resolve_{slot}")
    assert callable(cached_method)
    assert cached_method.__name__ == "<lambda>"


@pytest.mark.asyncio
async def test_async_singleton_uses_async_cached_method_replacement() -> None:
    calls = 0

    async def build_service() -> _SingletonService:
        nonlocal calls
        calls += 1
        return _SingletonService()

    container = Container()
    container.register_factory(
        _SingletonService,
        factory=build_service,
        lifetime=Lifetime.SINGLETON,
    )

    first = await container.aresolve(_SingletonService)
    second = await container.aresolve(_SingletonService)

    assert first is second
    assert calls == 1

    root_resolver = container._root_resolver
    assert root_resolver is not None
    slot = container._providers_registrations.get_by_type(_SingletonService).slot
    cached_method = getattr(root_resolver, f"aresolve_{slot}")
    assert inspect.iscoroutinefunction(cached_method)
    assert cached_method.__name__ == "_cached"


def test_transient_provider_is_not_cached() -> None:
    calls = 0

    def build_service() -> _TransientService:
        nonlocal calls
        calls += 1
        return _TransientService()

    container = Container()
    container.register_factory(
        _TransientService,
        factory=build_service,
        lifetime=Lifetime.TRANSIENT,
    )

    first = container.resolve(_TransientService)
    second = container.resolve(_TransientService)

    assert first is not second
    assert calls == 2


def test_scope_resolution_requires_explicit_opened_scope_chain() -> None:
    container = Container()
    container.register_concrete(
        _RequestService,
        concrete_type=_RequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireScopeMismatchError):
        container.resolve(_RequestService)

    with pytest.raises(DIWireScopeMismatchError):
        container.enter_scope(Scope.ACTION)

    with container.enter_scope() as request_scope:
        with request_scope.enter_scope(Scope.ACTION) as action_scope:
            from_request = request_scope.resolve(_RequestService)
            from_action = action_scope.resolve(_RequestService)
            assert from_request is from_action


def test_generated_dispatch_raises_for_unknown_dependency_in_sync_and_async_paths() -> None:
    container = Container()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(object)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        asyncio.run(container.aresolve(object))


def test_enter_scope_can_choose_skippable_or_next_non_skippable_scope() -> None:
    container = Container()
    container.register_concrete(
        _SessionService,
        concrete_type=_SessionService,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _RequestService,
        concrete_type=_RequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.SESSION) as session_scope:
        session_instance = session_scope.resolve(_SessionService)
        with session_scope.enter_scope() as request_scope:
            request_instance = request_scope.resolve(_RequestService)
            assert request_instance is request_scope.resolve(_RequestService)
        assert session_instance is session_scope.resolve(_SessionService)

    with container.enter_scope() as request_scope:
        assert isinstance(request_scope.resolve(_RequestService), _RequestService)
        with pytest.raises(DIWireScopeMismatchError):
            request_scope.resolve(_SessionService)


def test_enter_scope_returns_self_for_same_scope_and_rejects_non_forward_transition() -> None:
    container = Container()
    with container.enter_scope(Scope.SESSION) as session_scope:
        assert session_scope.enter_scope(Scope.SESSION) is session_scope

        with session_scope.enter_scope() as request_scope:
            assert request_scope.enter_scope(Scope.REQUEST) is request_scope
            with pytest.raises(DIWireScopeMismatchError, match="Cannot enter scope level"):
                request_scope.enter_scope(Scope.SESSION)


def test_enter_scope_from_deepest_scope_without_target_raises() -> None:
    container = Container()
    with container.enter_scope(Scope.SESSION) as session_scope:
        with session_scope.enter_scope() as request_scope:
            with request_scope.enter_scope() as action_scope:
                with action_scope.enter_scope() as step_scope:
                    with pytest.raises(DIWireScopeMismatchError, match="Cannot enter deeper scope"):
                        step_scope.enter_scope()


def test_request_resolver_delegates_to_session_owner_cache_when_opened_from_session() -> None:
    calls = 0

    def build_session_service() -> _SessionService:
        nonlocal calls
        calls += 1
        return _SessionService()

    container = Container()
    container.register_factory(
        _SessionService,
        factory=build_session_service,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.SESSION) as session_scope:
        session_instance = session_scope.resolve(_SessionService)
        with session_scope.enter_scope() as request_scope:
            delegated_instance = request_scope.resolve(_SessionService)
            delegated_again = request_scope.resolve(_SessionService)

    assert session_instance is delegated_instance
    assert delegated_instance is delegated_again
    assert calls == 1


@pytest.mark.asyncio
async def test_request_aresolve_for_async_session_service_raises_when_owner_missing() -> None:
    async def build_session_async_service() -> _SessionAsyncService:
        return _SessionAsyncService()

    container = Container()
    container.register_factory(
        _SessionAsyncService,
        factory=build_session_async_service,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
            await request_scope.aresolve(_SessionAsyncService)


@pytest.mark.asyncio
async def test_request_resolver_async_delegates_to_session_owner_cache() -> None:
    calls = 0

    async def build_session_async_service() -> _SessionAsyncService:
        nonlocal calls
        calls += 1
        return _SessionAsyncService()

    container = Container()
    container.register_factory(
        _SessionAsyncService,
        factory=build_session_async_service,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.SESSION) as session_scope:
        session_instance = await session_scope.aresolve(_SessionAsyncService)
        with session_scope.enter_scope() as request_scope:
            delegated_instance = await request_scope.aresolve(_SessionAsyncService)
            delegated_again = await request_scope.aresolve(_SessionAsyncService)

    assert session_instance is delegated_instance
    assert delegated_instance is delegated_again
    assert calls == 1


def test_renderer_emits_thread_locks_for_sync_graph() -> None:
    container = Container()
    container.register_factory(
        _SingletonService,
        factory=_SingletonService,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=True,
    )

    slot = container._providers_registrations.get_by_type(_SingletonService).slot
    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert f"_dep_{slot}_thread_lock" in code
    assert "_async_lock" not in code


@pytest.mark.asyncio
async def test_renderer_emits_async_locks_only_for_async_cached_paths() -> None:
    async def build_async() -> _SingletonService:
        return _SingletonService()

    container = Container()
    container.register_factory(
        _SingletonService,
        factory=build_async,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=True,
    )
    container.register_factory(
        _TransientService,
        factory=_TransientService,
        lifetime=Lifetime.SINGLETON,
        concurrency_safe=True,
    )

    async_slot = container._providers_registrations.get_by_type(_SingletonService).slot
    sync_slot = container._providers_registrations.get_by_type(_TransientService).slot

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert f"_dep_{async_slot}_async_lock" in code
    assert f"_dep_{sync_slot}_async_lock" not in code
    assert "_thread_lock" not in code

    resolved = await container.aresolve(_TransientService)
    assert isinstance(resolved, _TransientService)


def test_sync_generator_runs_cleanup_on_scope_exit() -> None:
    events: list[str] = []

    def provide_resource() -> Generator[_Resource, None, None]:
        events.append("enter")
        try:
            yield _Resource()
        finally:
            events.append("exit")

    container = Container()
    container.register_generator(
        _Resource,
        generator=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_Resource)
        assert isinstance(resolved, _Resource)
        assert events == ["enter"]

    assert events == ["enter", "exit"]


def test_sync_generator_cleanup_disabled_keeps_cleanup_callbacks_empty() -> None:
    events: list[str] = []

    def provide_resource() -> Generator[_Resource, None, None]:
        events.append("enter")
        yield _Resource()

    container = Container()
    container.register_generator(
        _Resource,
        generator=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    renderer = ResolversTemplateRenderer()
    code = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    build_root_resolver = cast("Any", namespace["build_root_resolver"])
    root_resolver = build_root_resolver(
        container._providers_registrations,
        cleanup_enabled=False,
    )

    request_scope = root_resolver.enter_scope()
    resolved = request_scope.resolve(_Resource)

    assert isinstance(resolved, _Resource)
    assert request_scope._cleanup_callbacks == []
    request_scope.__exit__(None, None, None)
    assert request_scope._cleanup_callbacks == []
    assert events == ["enter"]


@pytest.mark.asyncio
async def test_async_generator_runs_cleanup_on_async_scope_exit() -> None:
    events: list[str] = []

    async def provide_resource() -> AsyncGenerator[_Resource, None]:
        events.append("enter")
        try:
            yield _Resource()
        finally:
            events.append("exit")

    container = Container()
    container.register_generator(
        _Resource,
        generator=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_Resource)
        assert isinstance(resolved, _Resource)
        assert events == ["enter"]

    assert events == ["enter", "exit"]


def test_sync_resolution_for_async_generator_raises_async_dependency_error() -> None:
    async def provide_resource() -> AsyncGenerator[_Resource, None]:
        yield _Resource()

    container = Container()
    container.register_generator(_Resource, generator=provide_resource)

    with pytest.raises(
        DIWireAsyncDependencyInSyncContextError,
        match="requires asynchronous resolution",
    ):
        container.resolve(_Resource)


@pytest.mark.asyncio
async def test_async_context_manager_provider_uses_aenter_and_aexit() -> None:
    enter_calls = 0
    exit_calls = 0

    class _ManagedAsyncContext:
        async def __aenter__(self) -> _Resource:
            nonlocal enter_calls
            enter_calls += 1
            return _Resource()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            nonlocal exit_calls
            exit_calls += 1

    def provide_resource() -> AbstractAsyncContextManager[_Resource]:
        return _ManagedAsyncContext()

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_Resource)
        assert isinstance(resolved, _Resource)

    assert enter_calls == 1
    assert exit_calls == 1


def test_sync_scope_exit_raises_when_async_cleanup_callbacks_are_present() -> None:
    async def provide_resource() -> AsyncGenerator[_Resource, None]:
        yield _Resource()

    container = Container()
    container.register_generator(
        _Resource,
        generator=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(
        DIWireAsyncDependencyInSyncContextError,
        match="Cannot execute async cleanup in sync context",
    ):
        with container.enter_scope() as request_scope:
            asyncio.run(request_scope.aresolve(_Resource))


def test_cleanup_callbacks_execute_in_lifo_order() -> None:
    events: list[str] = []

    class _FirstContext:
        def __enter__(self) -> _Resource:
            events.append("first-enter")
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            events.append("first-exit")

    class _SecondContext:
        def __enter__(self) -> _SingletonService:
            events.append("second-enter")
            return _SingletonService()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            events.append("second-exit")

    def provide_first() -> _FirstContext:
        return _FirstContext()

    def provide_second() -> _SecondContext:
        return _SecondContext()

    class _Both:
        def __init__(self, first: _Resource, second: _SingletonService) -> None:
            self.first = first
            self.second = second

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_first,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_context_manager(
        _SingletonService,
        context_manager=provide_second,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _Both,
        concrete_type=_Both,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        request_scope.resolve(_Both)

    assert events == ["first-enter", "second-enter", "second-exit", "first-exit"]


def test_cleanup_keeps_first_cleanup_error_when_multiple_callbacks_fail() -> None:
    class _FirstContext:
        def __enter__(self) -> _Resource:
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            raise RuntimeError("first-exit-error")

    class _SecondContext:
        def __enter__(self) -> _SingletonService:
            return _SingletonService()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            raise RuntimeError("second-exit-error")

    def provide_first() -> _FirstContext:
        return _FirstContext()

    def provide_second() -> _SecondContext:
        return _SecondContext()

    class _Both:
        def __init__(self, first: _Resource, second: _SingletonService) -> None:
            self.first = first
            self.second = second

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_first,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_context_manager(
        _SingletonService,
        context_manager=provide_second,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _Both,
        concrete_type=_Both,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(RuntimeError, match="second-exit-error"):
        with container.enter_scope() as request_scope:
            request_scope.resolve(_Both)


def test_cleanup_does_not_override_active_body_exception() -> None:
    class _FailingContext:
        def __enter__(self) -> _Resource:
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            raise RuntimeError("cleanup boom")

    def provide_resource() -> _FailingContext:
        return _FailingContext()

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(ValueError, match="body boom"):
        with container.enter_scope() as request_scope:
            request_scope.resolve(_Resource)
            raise ValueError("body boom")


@pytest.mark.asyncio
async def test_async_cleanup_callbacks_execute_in_lifo_order_and_drain_stack() -> None:
    events: list[str] = []

    class _SyncContext:
        def __enter__(self) -> _Resource:
            events.append("sync-enter")
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            events.append("sync-exit")

    class _AsyncContext:
        async def __aenter__(self) -> _SingletonService:
            events.append("async-enter")
            return _SingletonService()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            events.append("async-exit")

    def provide_sync() -> _SyncContext:
        return _SyncContext()

    def provide_async() -> AbstractAsyncContextManager[_SingletonService]:
        return _AsyncContext()

    class _Both:
        def __init__(self, first: _Resource, second: _SingletonService) -> None:
            self.first = first
            self.second = second

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_sync,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_context_manager(
        _SingletonService,
        context_manager=provide_async,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _Both,
        concrete_type=_Both,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    request_scope: Any = None
    async with container.enter_scope() as opened_scope:
        request_scope = opened_scope
        await opened_scope.aresolve(_Both)

    assert events == ["sync-enter", "async-enter", "async-exit", "sync-exit"]
    assert request_scope._cleanup_callbacks == []


@pytest.mark.asyncio
async def test_async_cleanup_keeps_first_cleanup_error_when_multiple_callbacks_fail() -> None:
    class _FirstAsyncContext:
        async def __aenter__(self) -> _Resource:
            return _Resource()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            raise RuntimeError("first-async-exit-error")

    class _SecondAsyncContext:
        async def __aenter__(self) -> _SingletonService:
            return _SingletonService()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            raise RuntimeError("second-async-exit-error")

    def provide_first() -> AbstractAsyncContextManager[_Resource]:
        return _FirstAsyncContext()

    def provide_second() -> AbstractAsyncContextManager[_SingletonService]:
        return _SecondAsyncContext()

    class _Both:
        def __init__(self, first: _Resource, second: _SingletonService) -> None:
            self.first = first
            self.second = second

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_first,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_context_manager(
        _SingletonService,
        context_manager=provide_second,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _Both,
        concrete_type=_Both,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(RuntimeError, match="second-async-exit-error"):
        async with container.enter_scope() as request_scope:
            await request_scope.aresolve(_Both)


@pytest.mark.asyncio
async def test_async_cleanup_does_not_override_body_exception_and_forwards_exc_info() -> None:
    received: dict[str, object | None] = {
        "exc_type": None,
        "exc_value": None,
    }

    class _TrackingAsyncContext:
        async def __aenter__(self) -> _Resource:
            return _Resource()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            received["exc_type"] = exc_type
            received["exc_value"] = exc_value
            raise RuntimeError("async cleanup boom")

    def provide_resource() -> AbstractAsyncContextManager[_Resource]:
        return _TrackingAsyncContext()

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(ValueError, match="async body boom"):
        async with container.enter_scope() as request_scope:
            await request_scope.aresolve(_Resource)
            raise ValueError("async body boom")

    assert received["exc_type"] is ValueError
    assert isinstance(received["exc_value"], ValueError)


@pytest.mark.asyncio
async def test_async_generator_dependency_chain_requires_aresolve() -> None:
    async def provide_resource() -> AsyncGenerator[_Resource, None]:
        yield _Resource()

    def build_dependent(resource: _Resource) -> _DependsOnResource:
        return _DependsOnResource(resource)

    container = Container()
    container.register_generator(
        _Resource,
        generator=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_factory(
        _DependsOnResource,
        factory=build_dependent,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with pytest.raises(
            DIWireAsyncDependencyInSyncContextError,
            match="requires asynchronous resolution",
        ):
            request_scope.resolve(_DependsOnResource)

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_DependsOnResource)
        assert isinstance(resolved, _DependsOnResource)
        assert isinstance(resolved.resource, _Resource)


@pytest.mark.asyncio
async def test_async_context_manager_dependency_chain_requires_aresolve() -> None:
    @asynccontextmanager
    async def provide_resource() -> AsyncGenerator[_Resource, None]:
        yield _Resource()

    def build_dependent(resource: _Resource) -> _DependsOnResource:
        return _DependsOnResource(resource)

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_factory(
        _DependsOnResource,
        factory=build_dependent,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with pytest.raises(
            DIWireAsyncDependencyInSyncContextError,
            match="requires asynchronous resolution",
        ):
            request_scope.resolve(_DependsOnResource)

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_DependsOnResource)
        assert isinstance(resolved, _DependsOnResource)
        assert isinstance(resolved.resource, _Resource)


@pytest.mark.asyncio
async def test_async_scope_mismatch_raises_for_deeper_scoped_provider() -> None:
    container = Container()
    container.register_concrete(
        _RequestService,
        concrete_type=_RequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        await container.aresolve(_RequestService)


def test_positional_only_dependency_wiring_is_supported() -> None:
    dependency_instance = _PosOnlyDependency()

    def build_service(dependency: _PosOnlyDependency, /) -> _PosOnlyService:
        return _PosOnlyService(dependency)

    container = Container()
    container.register_instance(_PosOnlyDependency, instance=dependency_instance)
    container.register_factory(_PosOnlyService, factory=build_service)

    resolved = container.resolve(_PosOnlyService)

    assert isinstance(resolved, _PosOnlyService)
    assert resolved.dependency is dependency_instance


def test_var_positional_dependency_wiring_expands_iterable_dependency() -> None:
    def build_service(*values: int) -> _VarArgsService:
        return _VarArgsService(values)

    signature = inspect.signature(build_service)
    values_parameter = signature.parameters["values"]
    values_type = tuple[int, ...]
    values_instance = (1, 2, 3)

    container = Container()
    container.register_instance(provides=values_type, instance=values_instance)
    container.register_factory(
        _VarArgsService,
        factory=build_service,
        dependencies=[
            ProviderDependency(provides=values_type, parameter=values_parameter),
        ],
    )

    resolved = container.resolve(_VarArgsService)

    assert isinstance(resolved, _VarArgsService)
    assert resolved.values == values_instance


def test_var_keyword_dependency_wiring_expands_mapping_dependency() -> None:
    def build_service(**options: int) -> _KwArgsService:
        return _KwArgsService(options)

    signature = inspect.signature(build_service)
    options_parameter = signature.parameters["options"]
    options_type = dict[str, int]
    options_instance = {"first": 1, "second": 2}

    container = Container()
    container.register_instance(provides=options_type, instance=options_instance)
    container.register_factory(
        _KwArgsService,
        factory=build_service,
        dependencies=[
            ProviderDependency(provides=options_type, parameter=options_parameter),
        ],
    )

    resolved = container.resolve(_KwArgsService)

    assert isinstance(resolved, _KwArgsService)
    assert resolved.options == options_instance


def test_cleanup_raises_when_only_cleanup_fails() -> None:
    class _FailingContext:
        def __enter__(self) -> _Resource:
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            raise RuntimeError("cleanup boom")

    def provide_resource() -> _FailingContext:
        return _FailingContext()

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(RuntimeError, match="cleanup boom"):
        with container.enter_scope() as request_scope:
            request_scope.resolve(_Resource)


def test_cleanup_preserves_original_exception_and_forwards_exc_info() -> None:
    received: dict[str, object | None] = {
        "exc_type": None,
        "exc_value": None,
    }

    class _TrackingContext:
        def __enter__(self) -> _Resource:
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            received["exc_type"] = exc_type
            received["exc_value"] = exc_value
            raise RuntimeError("cleanup boom")

    def provide_resource() -> _TrackingContext:
        return _TrackingContext()

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(ValueError, match="original"):
        with container.enter_scope() as request_scope:
            request_scope.resolve(_Resource)
            raise ValueError("original")

    assert received["exc_type"] is ValueError
    assert isinstance(received["exc_value"], ValueError)


def test_build_root_resolver_supports_no_cleanup_mode() -> None:
    enter_calls = 0
    exit_calls = 0

    class _ManagedContext:
        def __enter__(self) -> _Resource:
            nonlocal enter_calls
            enter_calls += 1
            return _Resource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            nonlocal exit_calls
            exit_calls += 1

    def provide_resource() -> _ManagedContext:
        return _ManagedContext()

    container = Container()
    container.register_context_manager(
        _Resource,
        context_manager=provide_resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    renderer = ResolversTemplateRenderer()
    code = renderer.get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    build_root_resolver = cast("Any", namespace["build_root_resolver"])
    root_resolver = build_root_resolver(
        container._providers_registrations,
        cleanup_enabled=False,
    )
    request_scope = root_resolver.enter_scope()
    request_scope.resolve(_Resource)
    request_scope.__exit__(None, None, None)

    assert enter_calls == 1
    assert exit_calls == 0


def test_build_root_resolver_rebinds_globals_for_new_registrations() -> None:
    first = _Resource()
    second = _Resource()

    slot_counter = ProviderSpec.SLOT_COUNTER
    try:
        ProviderSpec.SLOT_COUNTER = 0
        first_container = Container()
        first_container.register_instance(_Resource, instance=first)

        ProviderSpec.SLOT_COUNTER = 0
        second_container = Container()
        second_container.register_instance(_Resource, instance=second)
    finally:
        ProviderSpec.SLOT_COUNTER = slot_counter

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=first_container._providers_registrations,
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    build_root_resolver = cast("Any", namespace["build_root_resolver"])

    first_resolver = build_root_resolver(first_container._providers_registrations)
    assert first_resolver.resolve(_Resource) is first

    second_resolver = build_root_resolver(second_container._providers_registrations)
    assert second_resolver.resolve(_Resource) is second

    # Already-cached value remains stable for the first resolver after global rebinding.
    assert first_resolver.resolve(_Resource) is first
