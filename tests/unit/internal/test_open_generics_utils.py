from __future__ import annotations

from typing import Any, Generic, TypeVar, cast

import pytest

from diwire import Lifetime, LockMode, Scope
from diwire._internal.open_generics import (
    OpenGenericRegistry,
    canonicalize_open_key,
    substitute_typevars,
)
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError

T = TypeVar("T")
U = TypeVar("U")


class _Box(Generic[T]):
    pass


class _Repository(Generic[T]):
    pass


class _Model:
    pass


class _User(_Model):
    pass


M = TypeVar("M", bound=_Model)
C = TypeVar("C", str, bytes)


class _ModelBox(Generic[M]):
    pass


class _ConstrainedBox(Generic[C]):
    pass


def _factory_a() -> object:
    return object()


def _factory_b() -> object:
    return object()


def test_canonicalization_treats_generic_class_and_open_alias_as_same_key() -> None:
    assert canonicalize_open_key(_Box) == _Box[T]
    assert canonicalize_open_key(_Box[T]) == _Box[T]


def test_substitute_typevars_handles_recursive_aliases() -> None:
    substituted = substitute_typevars(
        dict[str, list[T]],
        mapping={T: int},
    )
    assert substituted == dict[str, list[int]]


def test_registry_prefers_most_specific_template() -> None:
    registry = OpenGenericRegistry()
    registry.register(
        provides=_Repository[T],
        provider_kind="factory",
        provider=_factory_a,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )
    registry.register(
        provides=_Repository[list[T]],
        provider_kind="factory",
        provider=_factory_b,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    match = registry.find_best_match(_Repository[list[int]])

    assert match is not None
    assert match.spec.provider is _factory_b


def test_registry_resolves_ties_by_latest_registration() -> None:
    registry = OpenGenericRegistry()
    registry.register(
        provides=_Repository[tuple[T]],
        provider_kind="factory",
        provider=_factory_a,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )
    registry.register(
        provides=_Repository[tuple[U]],
        provider_kind="factory",
        provider=_factory_b,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    match = registry.find_best_match(_Repository[tuple[int]])

    assert match is not None
    assert match.spec.provider is _factory_b


def test_typevar_bound_validation_runs_during_match() -> None:
    registry = OpenGenericRegistry()
    registry.register(
        provides=_ModelBox[M],
        provider_kind="factory",
        provider=_factory_a,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    assert registry.find_best_match(_ModelBox[_User]) is not None
    invalid_key = cast("Any", _ModelBox)[str]
    with pytest.raises(DIWireInvalidGenericTypeArgumentError, match="bound"):
        registry.find_best_match(invalid_key)


def test_typevar_constraints_validation_runs_during_match() -> None:
    registry = OpenGenericRegistry()
    registry.register(
        provides=_ConstrainedBox[C],
        provider_kind="factory",
        provider=_factory_a,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        dependencies=[],
    )

    assert registry.find_best_match(_ConstrainedBox[str]) is not None
    invalid_key = cast("Any", _ConstrainedBox)[int]
    with pytest.raises(DIWireInvalidGenericTypeArgumentError, match="must satisfy one of"):
        registry.find_best_match(invalid_key)
