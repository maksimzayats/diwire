from __future__ import annotations

import inspect
from types import TracebackType
from typing import Any, cast

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireScopeMismatchError
from diwire.providers import Lifetime
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
