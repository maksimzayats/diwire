from __future__ import annotations

import builtins
import inspect
import threading
import typing
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import Annotated, Any, Generic, TypeVar, cast

import pytest
from typing_extensions import Self, TypeVar as TypeVarExt

from diwire import BaseScope, Lifetime, LockMode, Scope
from diwire._internal import open_generics
from diwire._internal.providers import ProviderDependency
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireScopeMismatchError,
)

T = TypeVar("T")
U = TypeVar("U")


class _Generic(Generic[T]):
    pass


class _Model:
    pass


class _User(_Model):
    pass


M = TypeVar("M", bound=_Model)
N = TypeVar("N", bound=_Model)


def _factory() -> object:
    return object()


class _MissingResolver:
    _cleanup_enabled = True

    def resolve(self, dependency: Any) -> Any:
        msg = f"missing dependency {dependency!r}"
        raise DIWireDependencyNotRegisteredError(msg)

    async def aresolve(self, dependency: Any) -> Any:
        msg = f"missing dependency {dependency!r}"
        raise DIWireDependencyNotRegisteredError(msg)

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: typing.Mapping[Any, Any] | None = None,
    ) -> _MissingResolver:
        _ = scope
        _ = context
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc_value
        _ = traceback

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc_value
        _ = traceback


def test_canonicalize_and_substitute_handle_aliases_without_arguments() -> None:
    assert open_generics.canonicalize_open_key(typing.Sequence) is None
    assert open_generics.substitute_typevars(typing.Sequence, mapping={}) == typing.Sequence


def test_validate_typevar_arguments_uses_generic_invalid_message_when_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(open_generics, "_is_type_argument_valid", lambda **_kwargs: False)

    with pytest.raises(DIWireInvalidGenericTypeArgumentError, match="is invalid"):
        open_generics.validate_typevar_arguments({TypeVar("X"): int})


def test_registry_validation_error_and_no_match_paths() -> None:
    registry = open_generics.OpenGenericRegistry()
    registry.register(
        provides=_Generic[M],
        provider_kind="factory",
        provider=_factory,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    invalid_key = cast("Any", _Generic)[str]
    with pytest.raises(DIWireInvalidGenericTypeArgumentError):
        registry.find_best_match(invalid_key)

    assert registry.find_best_match(list[int]) is None


def test_registry_handles_multiple_invalid_matches_after_first_validation_error() -> None:
    registry = open_generics.OpenGenericRegistry()
    registry.register(
        provides=_Generic[M],
        provider_kind="factory",
        provider=_factory,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )
    registry.register(
        provides=_Generic[N],
        provider_kind="factory",
        provider=_factory,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    invalid_key = cast("Any", _Generic)[str]
    with pytest.raises(DIWireInvalidGenericTypeArgumentError):
        registry.find_best_match(invalid_key)


def test_append_call_argument_supports_all_parameter_kinds_and_fallback() -> None:
    def _positional_only(value: int, /) -> None:
        _ = value

    def _positional_or_keyword(value: int) -> None:
        _ = value

    def _keyword_only(*, value: int) -> None:
        _ = value

    def _var_positional(*values: int) -> None:
        _ = values

    def _var_keyword(**values: int) -> None:
        _ = values

    positional_arguments: list[Any] = []
    keyword_arguments: dict[str, Any] = {}

    signatures = [
        inspect.signature(_positional_only),
        inspect.signature(_positional_or_keyword),
        inspect.signature(_keyword_only),
        inspect.signature(_var_positional),
        inspect.signature(_var_keyword),
    ]
    dependencies = [
        ProviderDependency(provides=int, parameter=signatures[0].parameters["value"]),
        ProviderDependency(provides=int, parameter=signatures[1].parameters["value"]),
        ProviderDependency(provides=int, parameter=signatures[2].parameters["value"]),
        ProviderDependency(provides=tuple[int, ...], parameter=signatures[3].parameters["values"]),
        ProviderDependency(provides=dict[str, int], parameter=signatures[4].parameters["values"]),
    ]

    open_generics._append_call_argument(
        dependency=dependencies[0],
        value=1,
        positional_arguments=positional_arguments,
        keyword_arguments=keyword_arguments,
    )
    open_generics._append_call_argument(
        dependency=dependencies[1],
        value=2,
        positional_arguments=positional_arguments,
        keyword_arguments=keyword_arguments,
    )
    open_generics._append_call_argument(
        dependency=dependencies[2],
        value=3,
        positional_arguments=positional_arguments,
        keyword_arguments=keyword_arguments,
    )
    open_generics._append_call_argument(
        dependency=dependencies[3],
        value=(4, 5),
        positional_arguments=positional_arguments,
        keyword_arguments=keyword_arguments,
    )
    open_generics._append_call_argument(
        dependency=dependencies[4],
        value={"six": 6},
        positional_arguments=positional_arguments,
        keyword_arguments=keyword_arguments,
    )

    class _UnknownParameter:
        name = "fallback"
        kind = object()

    class _UnknownDependency:
        parameter = _UnknownParameter()

    open_generics._append_call_argument(
        dependency=cast("Any", _UnknownDependency()),
        value=7,
        positional_arguments=positional_arguments,
        keyword_arguments=keyword_arguments,
    )

    assert positional_arguments == [1, 4, 5]
    assert keyword_arguments["value"] == 3
    assert keyword_arguments["six"] == 6
    assert keyword_arguments["fallback"] == 7


def test_cast_iterable_and_cast_mapping_raise_on_invalid_values() -> None:
    with pytest.raises(TypeError, match="Expected iterable value"):
        open_generics.cast_iterable(1)

    with pytest.raises(TypeError, match="Expected mapping value"):
        open_generics.cast_mapping(1)


def test_typevar_collection_matching_and_scoring_helpers_cover_edge_cases() -> None:
    found: list[TypeVar] = []
    open_generics._collect_typevars_into(value=_Generic, found=found)
    assert T in found

    mismatch = open_generics._match_typevars(template=tuple[T, T], concrete=tuple[int, str])
    assert mismatch is None
    assert open_generics._match_typevars(template=int, concrete=int) is not None
    assert open_generics._match_typevars(template=_Generic, concrete=_Generic[int]) is not None
    assert open_generics._match_typevars(template=list[T], concrete=dict[str, int]) is None
    assert open_generics._match_typevars(template=tuple[T, U], concrete=tuple[int]) is None

    assert open_generics._is_closed_generic_dependency(typing.Sequence) is False
    assert open_generics._specificity_score(int) == 2
    assert open_generics._specificity_score(typing.Sequence) == 2
    assert open_generics._normalize_generic_node(_Generic) == _Generic[T]
    assert (
        open_generics._rebuild_alias(origin=object(), args=(int,), fallback="fallback")
        == "fallback"
    )


def test_matches_type_constraint_handles_any_and_issubclass_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert open_generics._matches_type_constraint(argument=int, constraint=Any) is True
    assert open_generics._matches_type_constraint(argument=42, constraint=42) is True

    monkeypatch.setattr(builtins, "issubclass", lambda *_args: (_ for _ in ()).throw(TypeError()))
    assert open_generics._matches_type_constraint(argument=int, constraint=int) is False


def test_matches_type_constraint_handles_union_with_parameterized_generic() -> None:
    class _StateLike:
        pass

    constraint = typing.Mapping[str, Any] | _StateLike

    assert (
        open_generics._matches_type_constraint(argument=_StateLike, constraint=constraint) is True
    )
    assert (
        open_generics._matches_type_constraint(argument=dict[str, Any], constraint=constraint)
        is True
    )
    assert open_generics._matches_type_constraint(argument=int, constraint=constraint) is False


def test_typevar_default_helpers_cover_missing_and_unresolved_defaults() -> None:
    class _NoDefaultAttribute:
        pass

    class NoDefaultType:
        pass

    class _NoDefaultSentinel:
        __default__ = NoDefaultType()

    assert (
        open_generics._typevar_default_or_missing(cast("Any", _NoDefaultAttribute()))
        is open_generics._MISSING_TYPEVAR_DEFAULT
    )
    assert (
        open_generics._typevar_default_or_missing(cast("Any", _NoDefaultSentinel()))
        is open_generics._MISSING_TYPEVAR_DEFAULT
    )

    unresolved = TypeVar("unresolved")
    defaulted = TypeVarExt("defaulted", default=unresolved)

    class _DefaultedGeneric(Generic[defaulted]):
        pass

    assert open_generics._close_generic_dependency_with_typevar_defaults(_DefaultedGeneric) is (
        _DefaultedGeneric
    )


def test_resolve_scope_transition_path_handles_all_error_and_success_paths() -> None:
    with pytest.raises(DIWireScopeMismatchError, match="Cannot enter deeper scope"):
        open_generics._resolve_scope_transition_path(
            root_scope=Scope.APP,
            current_scope_level=Scope.STEP.level,
            scope=None,
        )

    assert open_generics._resolve_scope_transition_path(
        root_scope=Scope.APP,
        current_scope_level=Scope.APP.level,
        scope=None,
    ) == [Scope.REQUEST]
    assert open_generics._resolve_scope_transition_path(
        root_scope=Scope.APP,
        current_scope_level=Scope.APP.level,
        scope=Scope.SESSION,
    ) == [Scope.SESSION]
    assert open_generics._resolve_scope_transition_path(
        root_scope=Scope.APP,
        current_scope_level=Scope.APP.level,
        scope=Scope.ACTION,
    ) == [Scope.REQUEST, Scope.ACTION]
    assert (
        open_generics._resolve_scope_transition_path(
            root_scope=Scope.APP,
            current_scope_level=Scope.REQUEST.level,
            scope=Scope.REQUEST,
        )
        == []
    )

    with pytest.raises(DIWireScopeMismatchError, match="Cannot enter scope level"):
        open_generics._resolve_scope_transition_path(
            root_scope=Scope.APP,
            current_scope_level=Scope.REQUEST.level,
            scope=Scope.SESSION,
        )

    with pytest.raises(DIWireScopeMismatchError, match="is not a valid next transition"):
        open_generics._resolve_scope_transition_path(
            root_scope=Scope.APP,
            current_scope_level=Scope.APP.level,
            scope=BaseScope(99),
        )


def test_cleanup_helpers_handle_sync_async_and_error_aggregation() -> None:
    sync_called: list[str] = []
    async_called: list[str] = []

    def _sync_cleanup(
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: Any,
    ) -> None:
        sync_called.append("sync")

    async def _async_cleanup(
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: Any,
    ) -> None:
        async_called.append("async")

    open_generics._execute_sync_cleanup_callbacks(
        callbacks=[(0, _sync_cleanup)],
        exc_type=None,
        exc_value=None,
        traceback=None,
    )
    assert sync_called == ["sync"]

    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        open_generics._execute_sync_cleanup_callbacks(
            callbacks=[(1, _async_cleanup)],
            exc_type=None,
            exc_value=None,
            traceback=None,
        )

    open_generics._execute_sync_cleanup_callbacks(
        callbacks=[(1, _async_cleanup), (0, _sync_cleanup)],
        exc_type=RuntimeError,
        exc_value=RuntimeError(),
        traceback=None,
    )

    async def _run_async_cleanup() -> None:
        await open_generics._execute_async_cleanup_callbacks(
            callbacks=[(0, _sync_cleanup), (1, _async_cleanup)],
            exc_type=None,
            exc_value=None,
            traceback=None,
        )

    import asyncio

    asyncio.run(_run_async_cleanup())
    assert "async" in async_called

    async def _run_async_cleanup_failure() -> None:
        def _failing_cleanup(
            _exc_type: type[BaseException] | None,
            _exc_value: BaseException | None,
            _traceback: Any,
        ) -> None:
            raise ValueError("boom")

        await open_generics._execute_async_cleanup_callbacks(
            callbacks=[(0, _failing_cleanup), (0, _failing_cleanup)],
            exc_type=None,
            exc_value=None,
            traceback=None,
        )

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(_run_async_cleanup_failure())


def test_provider_cast_helpers_and_async_cleanup_error_helper_raise() -> None:
    with pytest.raises(TypeError, match="Expected concrete type provider"):
        open_generics._as_provider_type(1)
    with pytest.raises(TypeError, match="Expected factory provider"):
        open_generics._as_factory_provider(1)
    with pytest.raises(TypeError, match="Expected generator provider"):
        open_generics._as_generator_provider(1)
    with pytest.raises(TypeError, match="Expected context manager provider"):
        open_generics._as_context_manager_provider(1)
    with pytest.raises(DIWireAsyncDependencyInSyncContextError):
        open_generics._raise_async_cleanup_in_sync_context()


def test_open_generic_resolver_dispatch_cache_uses_normalized_key_and_materialization_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = open_generics.OpenGenericRegistry()
    registry.register(
        provides=_Generic[T],
        provider_kind="factory",
        provider=_factory,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    find_best_match_calls = 0
    original_find_best_match = registry.find_best_match

    def _counting_find_best_match(dependency: Any) -> Any:
        nonlocal find_best_match_calls
        find_best_match_calls += 1
        return original_find_best_match(dependency)

    monkeypatch.setattr(registry, "find_best_match", _counting_find_best_match)

    callback_calls = 0

    def _failing_callback(dependency: Any, match: Any) -> None:
        nonlocal callback_calls
        callback_calls += 1
        _ = dependency
        _ = match
        raise RuntimeError("materialization failed")

    resolver = open_generics.OpenGenericResolver(
        base_resolver=cast("Any", _MissingResolver()),
        registry=registry,
        root_scope=Scope.APP,
        has_async_specs=False,
        scope_level=Scope.APP.level,
        materialize_closed_callback=_failing_callback,
    )
    dependency = Annotated[_Generic[int], "meta"]

    with pytest.raises(RuntimeError, match="Open generic materialization failed"):
        resolver.resolve(dependency)

    second = resolver.resolve(dependency)

    assert find_best_match_calls == 2
    assert callback_calls == 1
    assert second is not None


@pytest.mark.asyncio
async def test_open_generic_resolver_async_dispatch_cache_reuses_match() -> None:
    registry = open_generics.OpenGenericRegistry()
    registry.register(
        provides=_Generic[T],
        provider_kind="factory",
        provider=_factory,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    resolver = open_generics.OpenGenericResolver(
        base_resolver=cast("Any", _MissingResolver()),
        registry=registry,
        root_scope=Scope.APP,
        has_async_specs=False,
        scope_level=Scope.APP.level,
    )

    first = await resolver.aresolve(_Generic[int])
    second = await resolver.aresolve(_Generic[int])

    assert first is not second


def test_open_generic_resolver_thread_lock_first_touch_is_singleton_under_concurrency() -> None:
    resolver = open_generics.OpenGenericResolver(
        base_resolver=cast("Any", _MissingResolver()),
        registry=open_generics.OpenGenericRegistry(),
        root_scope=Scope.APP,
        has_async_specs=False,
        scope_level=Scope.APP.level,
    )
    dependency = _Generic[int]
    barrier = threading.Barrier(24)

    def _resolve_thread_lock() -> Any:
        barrier.wait()
        return resolver.get_thread_lock(dependency)

    with ThreadPoolExecutor(max_workers=24) as executor:
        futures = [executor.submit(_resolve_thread_lock) for _ in range(24)]
        locks = [future.result() for future in futures]

    assert len({id(lock) for lock in locks}) == 1


def test_open_generic_child_local_state_is_isolated_during_concurrent_first_touch() -> None:
    resolver = open_generics.OpenGenericResolver(
        base_resolver=cast("Any", _MissingResolver()),
        registry=open_generics.OpenGenericRegistry(),
        root_scope=Scope.APP,
        has_async_specs=False,
        scope_level=Scope.APP.level,
    )
    first_child = resolver.enter_scope(Scope.REQUEST)
    second_child = resolver.enter_scope(Scope.REQUEST)
    dependency = _Generic[int]
    barrier = threading.Barrier(24)

    def _resolve_thread_lock(child: Any) -> Any:
        barrier.wait()
        return child.get_thread_lock(dependency)

    children = [first_child, second_child] * 12
    with ThreadPoolExecutor(max_workers=len(children)) as executor:
        locks = list(executor.map(_resolve_thread_lock, children))

    first_locks = locks[::2]
    second_locks = locks[1::2]
    assert len({id(lock) for lock in first_locks}) == 1
    assert len({id(lock) for lock in second_locks}) == 1
    assert first_locks[0] is not second_locks[0]

    first_child.set_cached(dependency=dependency, value="first")
    second_child.set_cached(dependency=dependency, value="second")
    assert first_child.get_cached(dependency) == "first"
    assert second_child.get_cached(dependency) == "second"

    first_async_lock = first_child.get_async_lock(dependency)
    second_async_lock = second_child.get_async_lock(dependency)
    assert first_child.get_async_lock(dependency) is first_async_lock
    assert second_child.get_async_lock(dependency) is second_async_lock
    assert first_async_lock is not second_async_lock

    cleanup_events: list[str] = []
    first_child._register_cleanup(
        kind=0,
        callback=lambda *_args: cleanup_events.append("first"),
    )
    second_child._register_cleanup(
        kind=0,
        callback=lambda *_args: cleanup_events.append("second"),
    )
    first_child.close()
    assert cleanup_events == ["first"]
    second_child.close()
    assert cleanup_events == ["first", "second"]


def test_open_generic_resolver_cache_first_touch_preserves_concurrent_writes() -> None:
    resolver = open_generics.OpenGenericResolver(
        base_resolver=cast("Any", _MissingResolver()),
        registry=open_generics.OpenGenericRegistry(),
        root_scope=Scope.APP,
        has_async_specs=False,
        scope_level=Scope.APP.level,
    )
    dependencies = [f"dep-{index}" for index in range(48)]
    barrier = threading.Barrier(len(dependencies))

    def _cache_dependency(dependency: str) -> None:
        barrier.wait()
        resolver.set_cached(dependency=dependency, value=dependency)

    with ThreadPoolExecutor(max_workers=len(dependencies)) as executor:
        list(executor.map(_cache_dependency, dependencies))

    for dependency in dependencies:
        assert resolver.get_cached(dependency) == dependency


def test_open_generic_resolver_materialization_callback_runs_once_under_concurrency() -> None:
    registry = open_generics.OpenGenericRegistry()
    registry.register(
        provides=_Generic[T],
        provider_kind="factory",
        provider=_factory,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    callback_calls = 0
    callback_lock = threading.Lock()
    callback_entered = threading.Event()
    callback_release = threading.Event()

    def _materialize_callback(dependency: Any, match: Any) -> None:
        nonlocal callback_calls
        _ = dependency
        _ = match
        with callback_lock:
            callback_calls += 1
        callback_entered.set()
        callback_release.wait(timeout=5)

    resolver = open_generics.OpenGenericResolver(
        base_resolver=cast("Any", _MissingResolver()),
        registry=registry,
        root_scope=Scope.APP,
        has_async_specs=False,
        scope_level=Scope.APP.level,
        materialize_closed_callback=_materialize_callback,
    )
    dependency = _Generic[int]
    barrier = threading.Barrier(16)

    def _resolve_dependency() -> Any:
        barrier.wait()
        return resolver.resolve(dependency)

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_resolve_dependency) for _ in range(16)]
        assert callback_entered.wait(timeout=5)
        callback_release.set()
        resolved_values = [future.result() for future in futures]

    assert callback_calls == 1
    assert len(resolved_values) == 16
