from __future__ import annotations

import inspect
from typing import Any, Generic, TypeVar, cast

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError
from diwire.markers import FromContext, Injected, Maybe, Provider
from diwire.providers import Lifetime
from diwire.scope import Scope


class _MaybeDependency:
    pass


class _MissingNestedDependency:
    pass


class _BrokenService:
    def __init__(self, dependency: _MissingNestedDependency) -> None:
        self.dependency = dependency


_DEFAULT_SENTINEL = object()
_INJECT_DEFAULT_SENTINEL = object()
_SHIFT_DEFAULT_SENTINEL = object()
_POSITIONAL_ONLY_DEFAULT_SENTINEL = object()


class _OptionalDefaultConsumer:
    def __init__(self, dependency: Maybe[_MaybeDependency] = _DEFAULT_SENTINEL) -> None:
        self.dependency = dependency


class _OptionalNoneConsumer:
    def __init__(self, dependency: Maybe[_MaybeDependency]) -> None:
        self.dependency = dependency


class _RequestScopedDependency:
    pass


class _ShiftedOptionalResult:
    def __init__(self, dependency: object, value: int) -> None:
        self.dependency = dependency
        self.value = value


def _build_shifted_optional_result(
    dependency: Maybe[_MaybeDependency] = _SHIFT_DEFAULT_SENTINEL,
    value: int = 5,
) -> _ShiftedOptionalResult:
    return _ShiftedOptionalResult(dependency=dependency, value=value)


class _PositionalOnlyOptionalResult:
    def __init__(self, dependency: object, value: int) -> None:
        self.dependency = dependency
        self.value = value


def _build_positional_only_optional_result(
    dependency: Maybe[_MaybeDependency] = _POSITIONAL_ONLY_DEFAULT_SENTINEL,
    value: int = 5,
    /,
) -> _PositionalOnlyOptionalResult:
    return _PositionalOnlyOptionalResult(dependency=dependency, value=value)


def _build_varargs_optional_result(*values: int) -> tuple[int, ...]:
    return values


def _build_kwargs_optional_result(**values: int) -> dict[str, int]:
    return values


T = TypeVar("T")


class _MaybeBox(Generic[T]):
    pass


class _MaybeBoxImpl(_MaybeBox[T]):
    def __init__(self, type_arg: type[T]) -> None:
        self.type_arg = type_arg


def _strict_container() -> Container:
    return Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=False,
    )


def test_resolve_maybe_returns_none_for_unregistered_dependency_in_strict_mode() -> None:
    container = _strict_container()

    assert container.resolve(Maybe[_MaybeDependency]) is None


def test_resolve_maybe_returns_registered_dependency_value() -> None:
    container = _strict_container()
    dependency = _MaybeDependency()
    container.add_instance(dependency, provides=_MaybeDependency)

    assert container.resolve(Maybe[_MaybeDependency]) is dependency


def test_resolve_maybe_propagates_nested_registration_errors() -> None:
    container = _strict_container()
    container.add_concrete(_BrokenService, provides=_BrokenService)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(Maybe[_BrokenService])


def test_missing_maybe_dependency_uses_constructor_default() -> None:
    container = _strict_container()
    container.add_concrete(_OptionalDefaultConsumer, provides=_OptionalDefaultConsumer)

    resolved = container.resolve(_OptionalDefaultConsumer)

    assert resolved.dependency is _DEFAULT_SENTINEL


def test_missing_maybe_dependency_without_default_injects_none() -> None:
    container = _strict_container()
    container.add_concrete(_OptionalNoneConsumer, provides=_OptionalNoneConsumer)

    resolved = container.resolve(_OptionalNoneConsumer)

    assert resolved.dependency is None


def test_registered_maybe_dependency_overrides_constructor_default() -> None:
    container = _strict_container()
    dependency = _MaybeDependency()
    container.add_instance(dependency, provides=_MaybeDependency)
    container.add_concrete(_OptionalDefaultConsumer, provides=_OptionalDefaultConsumer)

    resolved = container.resolve(_OptionalDefaultConsumer)

    assert resolved.dependency is dependency


def test_inject_maybe_dependency_uses_default_when_missing_and_overrides_when_registered() -> None:
    container = _strict_container()

    @container.inject
    def handler(
        dependency: Injected[Maybe[_MaybeDependency]] = _INJECT_DEFAULT_SENTINEL,
    ) -> object:
        return dependency

    injected_handler = cast("Any", handler)
    assert injected_handler() is _INJECT_DEFAULT_SENTINEL

    dependency = _MaybeDependency()
    container.add_instance(dependency, provides=_MaybeDependency)
    assert injected_handler() is dependency


def test_inject_scope_inference_uses_inner_dependency_scope_for_maybe() -> None:
    container = _strict_container()
    container.add_concrete(
        _RequestScopedDependency,
        provides=_RequestScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject(auto_open_scope=True)
    def handler(
        dependency: Injected[Maybe[_RequestScopedDependency]],
    ) -> _RequestScopedDependency | None:
        return dependency

    injected_handler = cast("Any", handler)
    resolved = injected_handler()
    assert isinstance(resolved, _RequestScopedDependency)


def test_resolve_maybe_closed_generic_uses_open_generic_registration_match() -> None:
    container = _strict_container()
    container.add_concrete(_MaybeBoxImpl, provides=_MaybeBox)

    resolved = container.resolve(Maybe[_MaybeBox[int]])

    assert isinstance(resolved, _MaybeBoxImpl)
    assert resolved.type_arg is int


def test_resolve_maybe_from_context_returns_none_only_when_context_key_is_missing() -> None:
    container = _strict_container()
    container.add_concrete(_MaybeBoxImpl, provides=_MaybeBox)

    with container.enter_scope(Scope.REQUEST) as request_scope:
        assert request_scope.resolve(Maybe[FromContext[int]]) is None

    with container.enter_scope(Scope.REQUEST, context={int: 7}) as request_scope:
        assert request_scope.resolve(Maybe[FromContext[int]]) == 7


def test_resolve_maybe_provider_token_keeps_provider_semantics() -> None:
    container = _strict_container()

    dependency_provider = container.resolve(Maybe[Provider[_MaybeDependency]])
    assert callable(dependency_provider)
    with pytest.raises(DIWireDependencyNotRegisteredError):
        dependency_provider()


def test_optional_union_has_no_special_resolution_semantics() -> None:
    container = _strict_container()

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(_MaybeDependency | None)


def test_missing_optional_positional_or_keyword_dependency_uses_keywords_for_following_arguments() -> (
    None
):
    signature = inspect.signature(_build_shifted_optional_result)
    container = _strict_container()
    container.add_instance(99, provides=int)
    container.add_factory(
        _build_shifted_optional_result,
        provides=_ShiftedOptionalResult,
        dependencies={
            Maybe[_MaybeDependency]: signature.parameters["dependency"],
            int: signature.parameters["value"],
        },
    )

    resolved = container.resolve(_ShiftedOptionalResult)

    assert resolved.dependency is _SHIFT_DEFAULT_SENTINEL
    assert resolved.value == 99


def test_missing_optional_positional_only_dependency_omits_subsequent_positional_only_arguments() -> (
    None
):
    signature = inspect.signature(_build_positional_only_optional_result)
    container = _strict_container()
    container.add_instance(99, provides=int)
    container.add_factory(
        _build_positional_only_optional_result,
        provides=_PositionalOnlyOptionalResult,
        dependencies={
            Maybe[_MaybeDependency]: signature.parameters["dependency"],
            int: signature.parameters["value"],
        },
    )

    resolved = container.resolve(_PositionalOnlyOptionalResult)

    assert resolved.dependency is _POSITIONAL_ONLY_DEFAULT_SENTINEL
    assert resolved.value == 5


def test_missing_optional_varargs_dependency_resolves_to_empty_tuple_literal() -> None:
    signature = inspect.signature(_build_varargs_optional_result)
    container = _strict_container()
    container.add_factory(
        _build_varargs_optional_result,
        provides=tuple[int, ...],
        dependencies={
            Maybe[_MaybeDependency]: signature.parameters["values"],
        },
    )

    resolved = container.resolve(tuple[int, ...])

    assert resolved == ()


def test_missing_optional_kwargs_dependency_resolves_to_empty_dict_literal() -> None:
    signature = inspect.signature(_build_kwargs_optional_result)
    container = _strict_container()
    container.add_factory(
        _build_kwargs_optional_result,
        provides=dict[str, int],
        dependencies={
            Maybe[_MaybeDependency]: signature.parameters["values"],
        },
    )

    resolved = container.resolve(dict[str, int])

    assert resolved == {}
