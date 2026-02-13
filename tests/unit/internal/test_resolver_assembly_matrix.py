from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from types import TracebackType
from typing import Any, cast

import pytest

from diwire import Container, Lifetime, LockMode, Scope
from diwire._internal.resolvers.assembly.renderer import ResolversAssemblyRenderer
from diwire.exceptions import DIWireAsyncDependencyInSyncContextError, DIWireScopeMismatchError


class _MatrixService:
    def __init__(self) -> None:
        self.value: object | None = None


class _MatrixResource:
    pass


class _MatrixAsyncDependency:
    pass


class _SignatureService:
    def __init__(self, payload: object) -> None:
        self.payload = payload


def _build_resolver_with_cleanup_mode(
    *,
    container: Container,
    cleanup_enabled: bool,
) -> Any:
    code = ResolversAssemblyRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    build_root_resolver = cast("Any", namespace["build_root_resolver"])
    return build_root_resolver(
        container._providers_registrations,
        cleanup_enabled=cleanup_enabled,
    )


@pytest.mark.parametrize(
    ("provider_kind", "lifetime", "scope", "expect_same", "expect_call_count"),
    [
        ("instance", None, Scope.APP, True, None),
        ("concrete", Lifetime.TRANSIENT, Scope.APP, False, None),
        ("factory", Lifetime.SCOPED, Scope.APP, True, 1),
        ("factory", Lifetime.TRANSIENT, Scope.REQUEST, False, 2),
        ("factory", Lifetime.SCOPED, Scope.REQUEST, True, 1),
    ],
)
def test_assembly_matrix_caching_identity_by_kind_lifetime_scope(
    provider_kind: str,
    lifetime: Lifetime | None,
    scope: Scope,
    expect_same: Any,
    expect_call_count: int | None,
) -> None:
    calls = 0

    def build_service() -> _MatrixService:
        nonlocal calls
        calls += 1
        service = _MatrixService()
        service.value = calls
        return service

    container = Container()
    if provider_kind == "instance":
        instance = _MatrixService()
        instance.value = "instance"
        container.add_instance(instance, provides=_MatrixService)
    elif provider_kind == "concrete":
        assert lifetime is not None
        container.add(
            _MatrixService,
            provides=_MatrixService,
            lifetime=lifetime,
            scope=scope,
        )
    else:
        assert lifetime is not None
        container.add_factory(
            build_service,
            provides=_MatrixService,
            lifetime=lifetime,
            scope=scope,
        )

    if scope is Scope.APP:
        first = container.resolve(_MatrixService)
        second = container.resolve(_MatrixService)
    else:
        with container.enter_scope() as request_scope:
            first = request_scope.resolve(_MatrixService)
            second = request_scope.resolve(_MatrixService)

    assert (first is second) is bool(expect_same)
    if expect_call_count is not None:
        assert calls == expect_call_count


def test_assembly_matrix_scoped_cache_isolated_across_scope_instances() -> None:
    calls = 0

    def build_service() -> _MatrixService:
        nonlocal calls
        calls += 1
        service = _MatrixService()
        service.value = calls
        return service

    container = Container()
    container.add_factory(
        build_service,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as first_scope:
        first = first_scope.resolve(_MatrixService)
        assert first is first_scope.resolve(_MatrixService)

    with container.enter_scope() as second_scope:
        second = second_scope.resolve(_MatrixService)
        assert second is second_scope.resolve(_MatrixService)

    assert first is not second
    assert calls == 2


@pytest.mark.parametrize("provider_kind", ["generator", "context_manager"])
@pytest.mark.parametrize("cleanup_enabled", [True, False])
def test_assembly_matrix_cleanup_behavior_respects_cleanup_enabled(
    provider_kind: str,
    cleanup_enabled: Any,
) -> None:
    events: list[str] = []
    exit_calls = 0

    def provide_generator() -> Generator[_MatrixResource, None, None]:
        events.append("enter")
        try:
            yield _MatrixResource()
        finally:
            events.append("exit")

    class _ManagedContext:
        def __enter__(self) -> _MatrixResource:
            events.append("enter")
            return _MatrixResource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            nonlocal exit_calls
            exit_calls += 1
            events.append("exit")

    def provide_context_manager() -> _ManagedContext:
        return _ManagedContext()

    container = Container()
    if provider_kind == "generator":
        container.add_generator(
            provide_generator,
            provides=_MatrixResource,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )
    else:
        container.add_context_manager(
            provide_context_manager,
            provides=_MatrixResource,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )

    root_resolver = _build_resolver_with_cleanup_mode(
        container=container,
        cleanup_enabled=bool(cleanup_enabled),
    )
    request_scope = root_resolver.enter_scope()
    resolved = request_scope.resolve(_MatrixResource)

    assert isinstance(resolved, _MatrixResource)
    assert "enter" in events
    expected_callbacks = 1 if bool(cleanup_enabled) else 0
    assert len(request_scope._cleanup_callbacks) == expected_callbacks
    request_scope.__exit__(None, None, None)

    if provider_kind == "context_manager":
        assert exit_calls == expected_callbacks
    elif bool(cleanup_enabled):
        assert "exit" in events


def test_assembly_matrix_scope_mismatch_for_request_scoped_dependency_at_root() -> None:
    container = Container()
    container.add_factory(
        _MatrixService,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        container.resolve(_MatrixService)


@pytest.mark.asyncio
async def test_assembly_matrix_async_dependency_chain_requires_aresolve() -> None:
    async def provide_dependency() -> AsyncGenerator[_MatrixAsyncDependency, None]:
        yield _MatrixAsyncDependency()

    def build_consumer(dependency: _MatrixAsyncDependency) -> _MatrixService:
        service = _MatrixService()
        service.value = dependency
        return service

    container = Container()
    container.add_generator(
        provide_dependency,
        provides=_MatrixAsyncDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_consumer,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with pytest.raises(
            DIWireAsyncDependencyInSyncContextError,
            match="requires asynchronous resolution",
        ):
            request_scope.resolve(_MatrixService)

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_MatrixService)
        assert isinstance(resolved.value, _MatrixAsyncDependency)


@pytest.mark.parametrize(
    ("lock_mode", "has_thread_lock"),
    [
        (LockMode.THREAD, True),
        (LockMode.NONE, False),
    ],
)
def test_assembly_matrix_cached_sync_path_lock_generation_follows_lock_mode(
    lock_mode: LockMode,
    has_thread_lock: Any,
) -> None:
    container = Container()
    container.add_factory(
        _MatrixService,
        provides=_MatrixService,
        lifetime=Lifetime.SCOPED,
        lock_mode=lock_mode,
    )
    slot = container._providers_registrations.get_by_type(_MatrixService).slot

    generated = ResolversAssemblyRenderer().get_providers_code(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
    )

    assert (f"_dep_{slot}_thread_lock" in generated) is has_thread_lock


@pytest.mark.parametrize("signature_kind", ["positional", "positional_only", "keyword_only"])
def test_assembly_matrix_signature_wiring_for_required_parameters(signature_kind: str) -> None:
    def positional(value: int) -> _SignatureService:
        return _SignatureService(value)

    def positional_only(value: int, /) -> _SignatureService:
        return _SignatureService(value)

    def keyword_only(*, value: int) -> _SignatureService:
        return _SignatureService(value)

    builders: dict[str, Callable[..., _SignatureService]] = {
        "positional": positional,
        "positional_only": positional_only,
        "keyword_only": keyword_only,
    }
    builder = builders[signature_kind]
    signature = inspect.signature(builder)

    container = Container()
    container.add_instance(42, provides=int)
    container.add_factory(
        builder,
        provides=_SignatureService,
        dependencies={
            int: signature.parameters["value"],
        },
    )

    resolved = container.resolve(_SignatureService)

    assert resolved.payload == 42


@pytest.mark.parametrize("signature_kind", ["var_positional", "var_keyword"])
def test_assembly_matrix_signature_wiring_for_variadic_parameters(signature_kind: str) -> None:
    def var_positional(*values: int) -> _SignatureService:
        return _SignatureService(tuple(values))

    def var_keyword(**options: int) -> _SignatureService:
        return _SignatureService(dict(options))

    builders: dict[str, Callable[..., _SignatureService]] = {
        "var_positional": var_positional,
        "var_keyword": var_keyword,
    }
    builder = builders[signature_kind]
    signature = inspect.signature(builder)

    container = Container()
    values_type: Any
    if signature_kind == "var_positional":
        values_type = tuple[int, ...]
        payload: object = (1, 2, 3)
        parameter = signature.parameters["values"]
    else:
        values_type = dict[str, int]
        payload = {"first": 1, "second": 2}
        parameter = signature.parameters["options"]

    container.add_instance(cast("Any", payload), provides=values_type)
    container.add_factory(
        builder,
        provides=_SignatureService,
        dependencies={
            values_type: parameter,
        },
    )

    resolved = container.resolve(_SignatureService)

    assert resolved.payload == payload


@pytest.mark.asyncio
async def test_assembly_matrix_sync_only_graph_has_sync_async_parity() -> None:
    container = Container()
    container.add_factory(
        _sync_only_service,
        provides=_MatrixService,
        lifetime=Lifetime.SCOPED,
    )

    sync_resolved = container.resolve(_MatrixService)
    async_resolved = await container.aresolve(_MatrixService)

    assert sync_resolved is async_resolved
    assert async_resolved.value == "sync-only"


def _sync_only_service() -> _MatrixService:
    service = _MatrixService()
    service.value = "sync-only"
    return service
