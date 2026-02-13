from __future__ import annotations

import builtins
import inspect
import typing
from typing import Any, Generic, TypeVar, cast

import pytest

from diwire import BaseScope, Lifetime, LockMode, Scope
from diwire._internal import open_generics
from diwire._internal.providers import ProviderDependency
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
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
