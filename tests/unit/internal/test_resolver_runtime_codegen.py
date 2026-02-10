from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import AsyncGenerator, Callable, Generator
from concurrent.futures import ThreadPoolExecutor
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
from diwire.lock_mode import LockMode
from diwire.markers import Injected
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


class _InjectScopedDependency:
    pass


class _InjectScopedConsumer:
    def __init__(self, dependency: _InjectScopedDependency) -> None:
        self.dependency = dependency


class _InjectNestedInnerConsumer:
    def __init__(self, dependency: _InjectScopedDependency) -> None:
        self.dependency = dependency


class _InjectNestedOuterConsumer:
    def __init__(
        self,
        inner: _InjectNestedInnerConsumer,
        dependency: _InjectScopedDependency,
    ) -> None:
        self.inner = inner
        self.dependency = dependency


class _MixedSharedSyncDependency:
    pass


class _MixedSyncConsumer:
    def __init__(self, dependency: _MixedSharedSyncDependency) -> None:
        self.dependency = dependency


class _MixedAsyncGraphDependency:
    pass


def _new_list_int_alias() -> Any:
    return list[int]


def _new_dict_str_int_alias() -> Any:
    return dict[str, int]


def _new_tuple_int_var_alias() -> Any:
    return tuple[int, ...]


def _new_int_or_str_alias() -> Any:
    return int | str


def _bound_self(method: Any) -> Any:
    return cast("Any", method).__self__


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


def test_compile_returns_cached_resolver_and_rebinds_entrypoints() -> None:
    container = Container()
    container.register_instance(_Resource, instance=_Resource())

    initial_resolver = container._root_resolver
    assert initial_resolver is None
    assert _bound_self(container.resolve) is container
    assert _bound_self(container.aresolve) is container
    assert _bound_self(container.enter_scope) is container
    assert _bound_self(container.__enter__) is container
    assert _bound_self(container.__aenter__) is container
    assert _bound_self(container.__exit__) is container
    assert _bound_self(container.__aexit__) is container

    first_resolver = container.compile()
    second_resolver = container.compile()

    assert first_resolver is second_resolver
    assert container._root_resolver is first_resolver
    assert _bound_self(container.resolve) is first_resolver
    assert _bound_self(container.aresolve) is first_resolver
    assert _bound_self(container.enter_scope) is first_resolver
    assert _bound_self(container.__enter__) is container
    assert _bound_self(container.__aenter__) is container
    assert _bound_self(container.__exit__) is container
    assert _bound_self(container.__aexit__) is container


def test_resolve_auto_compiles_root_resolver_when_uncompiled() -> None:
    resource = _Resource()
    container = Container()
    container.register_instance(_Resource, instance=resource)

    initial_resolver = container._root_resolver
    assert initial_resolver is None

    resolved = container.resolve(_Resource)
    root_resolver = container._root_resolver

    assert resolved is resource
    assert root_resolver is not None
    assert _bound_self(container.resolve) is root_resolver


@pytest.mark.asyncio
async def test_aresolve_auto_compiles_root_resolver_when_uncompiled() -> None:
    resource = _Resource()
    container = Container()
    container.register_instance(_Resource, instance=resource)

    initial_resolver = container._root_resolver
    assert initial_resolver is None

    resolved = await container.aresolve(_Resource)
    root_resolver = container._root_resolver

    assert resolved is resource
    assert root_resolver is not None
    assert _bound_self(container.aresolve) is root_resolver


def test_enter_scope_auto_compiles_root_resolver_when_uncompiled() -> None:
    container = Container()
    container.register_concrete(
        _RequestService,
        concrete_type=_RequestService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    initial_resolver = container._root_resolver
    assert initial_resolver is None

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_RequestService)
        assert isinstance(resolved, _RequestService)

    root_resolver = container._root_resolver
    assert root_resolver is not None
    assert _bound_self(container.enter_scope) is root_resolver


def test_registering_after_compile_invalidates_compilation_and_rebinds_lazy_entrypoints() -> None:
    class _RegisteredByInstance:
        pass

    class _RegisteredByConcrete:
        pass

    class _RegisteredByFactory:
        pass

    class _RegisteredByGenerator:
        pass

    class _RegisteredByContextManager:
        pass

    def build_factory() -> _RegisteredByFactory:
        return _RegisteredByFactory()

    def build_generator() -> Generator[_RegisteredByGenerator, None, None]:
        yield _RegisteredByGenerator()

    class _ManagedContext:
        def __enter__(self) -> _RegisteredByContextManager:
            return _RegisteredByContextManager()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def build_context_manager() -> _ManagedContext:
        return _ManagedContext()

    container = Container()
    previous_resolver = container.compile()

    registrations: tuple[tuple[str, Any], ...] = (
        (
            "instance",
            lambda: container.register_instance(
                _RegisteredByInstance,
                instance=_RegisteredByInstance(),
            ),
        ),
        (
            "concrete",
            lambda: container.register_concrete(
                _RegisteredByConcrete,
                concrete_type=_RegisteredByConcrete,
            ),
        ),
        (
            "factory",
            lambda: container.register_factory(
                _RegisteredByFactory,
                factory=build_factory,
            ),
        ),
        (
            "generator",
            lambda: container.register_generator(
                _RegisteredByGenerator,
                generator=build_generator,
            ),
        ),
        (
            "context manager",
            lambda: container.register_context_manager(
                _RegisteredByContextManager,
                context_manager=build_context_manager,
            ),
        ),
    )

    for registration_name, register in registrations:
        register()

        assert container._root_resolver is None, registration_name
        assert _bound_self(container.resolve) is container, registration_name
        assert _bound_self(container.aresolve) is container, registration_name
        assert _bound_self(container.enter_scope) is container, registration_name
        assert _bound_self(container.__enter__) is container, registration_name
        assert _bound_self(container.__aenter__) is container, registration_name
        assert _bound_self(container.__exit__) is container, registration_name
        assert _bound_self(container.__aexit__) is container, registration_name

        compiled_resolver = container.compile()
        assert compiled_resolver is not previous_resolver, registration_name
        assert _bound_self(container.resolve) is compiled_resolver, registration_name
        assert _bound_self(container.aresolve) is compiled_resolver, registration_name
        assert _bound_self(container.enter_scope) is compiled_resolver, registration_name
        assert _bound_self(container.__enter__) is container, registration_name
        assert _bound_self(container.__aenter__) is container, registration_name
        assert _bound_self(container.__exit__) is container, registration_name
        assert _bound_self(container.__aexit__) is container, registration_name
        previous_resolver = compiled_resolver


def test_autoregister_keeps_container_entrypoints_and_skips_existing_registration() -> None:
    class _AutoRegisteredService:
        pass

    container = Container(autoregister=True)

    first = container.resolve(_AutoRegisteredService)
    root_resolver = container._root_resolver

    assert isinstance(first, _AutoRegisteredService)
    assert root_resolver is not None
    assert _bound_self(container.resolve) is container
    assert _bound_self(container.aresolve) is container
    assert _bound_self(container.enter_scope) is container
    assert _bound_self(container.__enter__) is container
    assert _bound_self(container.__aenter__) is container
    assert _bound_self(container.__exit__) is container
    assert _bound_self(container.__aexit__) is container

    second = container.resolve(_AutoRegisteredService)

    assert isinstance(second, _AutoRegisteredService)
    assert _bound_self(container.resolve) is container
    assert _bound_self(container.aresolve) is container
    assert _bound_self(container.enter_scope) is container
    assert _bound_self(container.__enter__) is container
    assert _bound_self(container.__aenter__) is container
    assert _bound_self(container.__exit__) is container
    assert _bound_self(container.__aexit__) is container
    assert container._root_resolver is root_resolver


def test_dunder_enter_and_exit_delegate_to_root_resolver() -> None:
    container = Container()
    container.register_instance(_Resource, instance=_Resource())

    entered = container.__enter__()
    root_resolver = container._root_resolver

    assert root_resolver is not None
    assert entered is root_resolver

    container.__exit__(None, None, None)


def test_dunder_exit_without_matching_enter_raises_runtime_error() -> None:
    container = Container()

    with pytest.raises(RuntimeError, match="without a matching enter"):
        container.__exit__(None, None, None)

    with pytest.raises(RuntimeError, match="without a matching enter"):
        container.close()


def test_container_exit_wrapper_delegates_when_root_resolver_exists() -> None:
    container = Container()
    container.register_instance(_Resource, instance=_Resource())
    container.compile()

    Container.__exit__(container, None, None, None)


@pytest.mark.asyncio
async def test_dunder_aenter_and_aexit_delegate_to_root_resolver() -> None:
    container = Container()
    container.register_instance(_Resource, instance=_Resource())

    entered = await container.__aenter__()
    root_resolver = container._root_resolver

    assert root_resolver is not None
    assert entered is root_resolver

    await container.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_dunder_aexit_without_matching_aenter_raises_runtime_error() -> None:
    container = Container()

    with pytest.raises(RuntimeError, match="without a matching enter"):
        await container.__aexit__(None, None, None)

    with pytest.raises(RuntimeError, match="without a matching enter"):
        await container.aclose()


@pytest.mark.asyncio
async def test_container_aexit_wrapper_delegates_when_root_resolver_exists() -> None:
    container = Container()
    container.register_instance(_Resource, instance=_Resource())
    container.compile()

    await Container.__aexit__(container, None, None, None)


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


def test_codegen_passes_resolver_to_inject_wrapped_provider_calls() -> None:
    container = Container()
    container.register_concrete(
        _InjectScopedDependency,
        concrete_type=_InjectScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    def build_consumer(
        dependency: Injected[_InjectScopedDependency],
    ) -> _InjectScopedConsumer:
        return _InjectScopedConsumer(dependency=dependency)

    container.register_factory(
        _InjectScopedConsumer,
        factory=build_consumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_InjectScopedConsumer)
        assert isinstance(resolved, _InjectScopedConsumer)
        assert isinstance(resolved.dependency, _InjectScopedDependency)


@pytest.mark.asyncio
async def test_codegen_async_inject_wrapper_provider_receives_resolver() -> None:
    container = Container()
    container.register_concrete(
        _InjectScopedDependency,
        concrete_type=_InjectScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    async def build_consumer(
        dependency: Injected[_InjectScopedDependency],
    ) -> _InjectScopedConsumer:
        await asyncio.sleep(0)
        return _InjectScopedConsumer(dependency=dependency)

    container.register_factory(
        _InjectScopedConsumer,
        factory=build_consumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_InjectScopedConsumer)

    assert isinstance(resolved, _InjectScopedConsumer)
    assert isinstance(resolved.dependency, _InjectScopedDependency)


def test_codegen_nested_inject_wrappers_runtime_scope_consistency() -> None:
    container = Container()
    container.register_concrete(
        _InjectScopedDependency,
        concrete_type=_InjectScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    def build_inner(
        dependency: Injected[_InjectScopedDependency],
    ) -> _InjectNestedInnerConsumer:
        return _InjectNestedInnerConsumer(dependency=dependency)

    @container.inject
    def build_outer(
        inner: Injected[_InjectNestedInnerConsumer],
        dependency: Injected[_InjectScopedDependency],
    ) -> _InjectNestedOuterConsumer:
        return _InjectNestedOuterConsumer(inner=inner, dependency=dependency)

    container.register_factory(
        _InjectNestedInnerConsumer,
        factory=build_inner,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_factory(
        _InjectNestedOuterConsumer,
        factory=build_outer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_InjectNestedOuterConsumer)

    assert isinstance(resolved, _InjectNestedOuterConsumer)
    assert resolved.inner.dependency is resolved.dependency


def test_codegen_inject_wrapper_singleton_thread_safe_stress() -> None:
    calls = 0
    workers = 32

    dependency = _Resource()
    container = Container()
    container.register_instance(_Resource, instance=dependency)

    @container.inject
    def build_singleton(resource: Injected[_Resource]) -> _DependsOnResource:
        nonlocal calls
        calls += 1
        return _DependsOnResource(resource=resource)

    container.register_factory(
        _DependsOnResource,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.THREAD,
    )
    container.compile()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(container.resolve, _DependsOnResource) for _ in range(workers * 2)]
        results = [future.result(timeout=5) for future in futures]

    assert calls == 1
    assert len({id(result) for result in results}) == 1


@pytest.mark.asyncio
async def test_codegen_inject_wrapper_singleton_async_stress() -> None:
    calls = 0
    tasks = 128
    dependency = _Resource()
    container = Container()
    container.register_instance(_Resource, instance=dependency)

    @container.inject
    async def build_singleton(resource: Injected[_Resource]) -> _DependsOnResource:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _DependsOnResource(resource=resource)

    container.register_factory(
        _DependsOnResource,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.ASYNC,
    )

    results = await asyncio.gather(
        *(container.aresolve(_DependsOnResource) for _ in range(tasks)),
    )

    assert calls == 1
    assert len({id(result) for result in results}) == 1


def test_codegen_inject_wrapper_unsafe_mode_stress_no_deadlock() -> None:
    calls = 0
    workers = 32
    all_started = threading.Event()
    calls_lock = threading.Lock()
    dependency = _Resource()
    container = Container()
    container.register_instance(_Resource, instance=dependency)

    @container.inject
    def build_singleton(resource: Injected[_Resource]) -> _DependsOnResource:
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls == workers:
                all_started.set()
        did_start = all_started.wait(timeout=2)
        assert did_start
        return _DependsOnResource(resource=resource)

    container.register_factory(
        _DependsOnResource,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.NONE,
    )
    container.compile()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(container.resolve, _DependsOnResource) for _ in range(workers)]
        results = [future.result(timeout=5) for future in futures]

    assert calls == workers
    assert all(isinstance(result, _DependsOnResource) for result in results)
    assert len({id(result) for result in results}) == workers
    assert container.resolve(_DependsOnResource) is container.resolve(_DependsOnResource)


def test_generated_dispatch_raises_for_unknown_dependency_in_sync_and_async_paths() -> None:
    container = Container()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(object)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        asyncio.run(container.aresolve(object))

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(_new_list_int_alias())

    with pytest.raises(DIWireDependencyNotRegisteredError):
        asyncio.run(container.aresolve(_new_list_int_alias()))


@pytest.mark.parametrize(
    "alias_factory",
    [
        _new_list_int_alias,
        _new_dict_str_int_alias,
        _new_tuple_int_var_alias,
        _new_int_or_str_alias,
    ],
)
def test_generated_dispatch_resolves_equal_non_identical_generic_alias_keys(
    alias_factory: Callable[[], Any],
) -> None:
    registration_key = alias_factory()
    lookup_key = alias_factory()
    instance = object()
    container = Container()
    container.register_instance(provides=registration_key, instance=instance)

    assert lookup_key == registration_key
    assert lookup_key is not registration_key
    assert container.resolve(lookup_key) is instance


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alias_factory",
    [
        _new_list_int_alias,
        _new_dict_str_int_alias,
        _new_tuple_int_var_alias,
        _new_int_or_str_alias,
    ],
)
async def test_generated_aresolve_resolves_equal_non_identical_generic_alias_keys(
    alias_factory: Callable[[], Any],
) -> None:
    registration_key = alias_factory()
    lookup_key = alias_factory()
    instance = object()
    container = Container()
    container.register_instance(provides=registration_key, instance=instance)

    assert lookup_key == registration_key
    assert lookup_key is not registration_key
    assert await container.aresolve(lookup_key) is instance


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


def test_request_resolve_for_sync_session_service_raises_when_owner_missing() -> None:
    container = Container()
    container.register_factory(
        _SessionService,
        factory=_SessionService,
        scope=Scope.SESSION,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
            request_scope.resolve(_SessionService)


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
    container = Container(lock_mode="auto")
    container.register_factory(
        _SingletonService,
        factory=_SingletonService,
        lifetime=Lifetime.SINGLETON,
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

    container = Container(lock_mode="auto")
    container.register_factory(
        _SingletonService,
        factory=build_async,
        lifetime=Lifetime.SINGLETON,
    )
    container.register_factory(
        _TransientService,
        factory=_TransientService,
        lifetime=Lifetime.SINGLETON,
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


def test_renderer_lock_mode_none_emits_no_lock_globals() -> None:
    container = Container()
    container.register_factory(
        _SingletonService,
        factory=_SingletonService,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.NONE,
    )

    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert "_thread_lock" not in code
    assert "_async_lock" not in code


def test_mixed_graph_thread_override_keeps_sync_singleton_thread_safe() -> None:
    calls = 0
    workers = 24

    def build_sync_singleton() -> _SingletonService:
        nonlocal calls
        calls += 1
        return _SingletonService()

    async def build_async_singleton() -> _TransientService:
        return _TransientService()

    container = Container()
    container.register_factory(
        _SingletonService,
        factory=build_sync_singleton,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.THREAD,
    )
    container.register_factory(
        _TransientService,
        factory=build_async_singleton,
        lifetime=Lifetime.SINGLETON,
    )
    container.compile()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(container.resolve, _SingletonService) for _ in range(workers * 2)]
        results = [future.result(timeout=5) for future in futures]

    assert calls == 1
    assert len({id(result) for result in results}) == 1


def test_mixed_graph_thread_override_keeps_sync_dependency_chain_thread_safe() -> None:
    shared_calls = 0
    consumer_calls = 0
    workers = 24

    def build_shared_dependency() -> _MixedSharedSyncDependency:
        nonlocal shared_calls
        shared_calls += 1
        return _MixedSharedSyncDependency()

    def build_consumer(dependency: _MixedSharedSyncDependency) -> _MixedSyncConsumer:
        nonlocal consumer_calls
        consumer_calls += 1
        return _MixedSyncConsumer(dependency=dependency)

    async def build_async_graph_dependency() -> _MixedAsyncGraphDependency:
        return _MixedAsyncGraphDependency()

    container = Container(lock_mode="auto")
    container.register_factory(
        _MixedSharedSyncDependency,
        factory=build_shared_dependency,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.THREAD,
    )
    container.register_factory(
        _MixedSyncConsumer,
        factory=build_consumer,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.THREAD,
    )
    container.register_factory(
        _MixedAsyncGraphDependency,
        factory=build_async_graph_dependency,
        lifetime=Lifetime.SINGLETON,
    )

    shared_slot = container._providers_registrations.get_by_type(_MixedSharedSyncDependency).slot
    consumer_slot = container._providers_registrations.get_by_type(_MixedSyncConsumer).slot
    async_slot = container._providers_registrations.get_by_type(_MixedAsyncGraphDependency).slot
    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert f"_dep_{shared_slot}_thread_lock" in code
    assert f"_dep_{consumer_slot}_thread_lock" in code
    assert f"_dep_{async_slot}_async_lock" in code

    container.compile()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(container.resolve, _MixedSyncConsumer) for _ in range(workers * 2)]
        results = [future.result(timeout=5) for future in futures]

    assert shared_calls == 1
    assert consumer_calls == 1
    assert len({id(result) for result in results}) == 1
    assert len({id(result.dependency) for result in results}) == 1


def test_lock_mode_async_on_sync_cached_provider_leaves_sync_path_unlocked() -> None:
    calls = 0
    workers = 12
    all_started = threading.Event()
    calls_lock = threading.Lock()

    def build_singleton() -> _SingletonService:
        nonlocal calls
        with calls_lock:
            calls += 1
            if calls == workers:
                all_started.set()
        did_start = all_started.wait(timeout=2)
        assert did_start
        return _SingletonService()

    container = Container()
    container.register_factory(
        _SingletonService,
        factory=build_singleton,
        lifetime=Lifetime.SINGLETON,
        lock_mode=LockMode.ASYNC,
    )
    slot = container._providers_registrations.get_by_type(_SingletonService).slot
    code = ResolversTemplateRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    assert f"_dep_{slot}_thread_lock" not in code
    container.compile()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(container.resolve, _SingletonService) for _ in range(workers)]
        results = [future.result(timeout=5) for future in futures]

    assert calls == workers
    assert len({id(result) for result in results}) == workers


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


def test_scope_chain_transitions_cover_session_request_action_and_step_paths() -> None:
    class _ActionService:
        pass

    class _StepService:
        pass

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
    container.register_concrete(
        _ActionService,
        concrete_type=_ActionService,
        scope=Scope.ACTION,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _StepService,
        concrete_type=_StepService,
        scope=Scope.STEP,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.SESSION) as session_scope:
        assert session_scope.enter_scope(Scope.SESSION) is session_scope
        with session_scope.enter_scope() as request_scope:
            assert request_scope.enter_scope(Scope.REQUEST) is request_scope
            with request_scope.enter_scope() as action_scope:
                assert action_scope.enter_scope(Scope.ACTION) is action_scope
                with action_scope.enter_scope() as step_scope:
                    with pytest.raises(DIWireScopeMismatchError, match="Cannot enter deeper scope"):
                        step_scope.enter_scope(Scope.STEP)
                    assert isinstance(step_scope.resolve(_SessionService), _SessionService)
                    assert isinstance(step_scope.resolve(_RequestService), _RequestService)
                    assert isinstance(step_scope.resolve(_ActionService), _ActionService)
                    assert isinstance(step_scope.resolve(_StepService), _StepService)


def test_build_root_resolver_rebind_loop_preserves_each_existing_resolver_cache() -> None:
    slot_counter = ProviderSpec.SLOT_COUNTER
    try:
        ProviderSpec.SLOT_COUNTER = 0
        template_source_container = Container()
        template_source_container.register_instance(_Resource, instance=_Resource())
        code = ResolversTemplateRenderer().get_providers_code(
            root_scope=Scope.APP,
            registrations=template_source_container._providers_registrations,
        )
        namespace: dict[str, object] = {}
        exec(code, namespace)  # noqa: S102
        build_root_resolver = cast("Any", namespace["build_root_resolver"])

        resolvers: list[Any] = []
        instances: list[_Resource] = []
        for _ in range(4):
            ProviderSpec.SLOT_COUNTER = 0
            container = Container()
            current = _Resource()
            container.register_instance(_Resource, instance=current)
            resolver = build_root_resolver(container._providers_registrations)
            assert resolver.resolve(_Resource) is current
            resolvers.append(resolver)
            instances.append(current)

        for resolver, expected in zip(resolvers, instances, strict=True):
            assert resolver.resolve(_Resource) is expected
    finally:
        ProviderSpec.SLOT_COUNTER = slot_counter
