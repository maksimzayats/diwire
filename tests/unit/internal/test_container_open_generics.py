from __future__ import annotations

import inspect
import typing
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Generic, TypeVar, cast

import pytest

from diwire.container import Container
from diwire.container_context import ContainerContext
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireScopeMismatchError,
)
from diwire.markers import Component, Injected
from diwire.providers import Lifetime, ProviderDependency
from diwire.scope import Scope

T = TypeVar("T")
U = TypeVar("U")


class _IBox(Generic[T]):
    pass


@dataclass(slots=True, kw_only=True)
class _KeywordBox(Generic[T]):
    type: type[T]


@dataclass(slots=True)
class _KeywordBoxImpl(_KeywordBox[T]):
    pass


@dataclass(slots=True)
class _KeywordSpecialIntBox(_KeywordBox[int]):
    pass


@dataclass
class _Box(_IBox[T]):
    type: type[T]


@dataclass
class _BoxA(_IBox[T]):
    type: type[T]


@dataclass
class _BoxB(_IBox[T]):
    type: type[T]


class _SpecialIntBox(_IBox[int]):
    def __init__(self) -> None:
        self.type = int


def _create_box(type_arg: type[T]) -> _IBox[T]:
    return _Box(type=type_arg)


async def _create_box_async(type_arg: type[T]) -> _IBox[T]:
    return _Box(type=type_arg)


def _generate_box(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
    yield _Box(type=type_arg)


@contextmanager
def _context_box(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
    yield _Box(type=type_arg)


@asynccontextmanager
async def _async_context_box(type_arg: type[T]) -> AsyncGenerator[_IBox[T], None]:
    yield _Box(type=type_arg)


def test_open_key_canonicalization_allows_latest_override_for_equivalent_keys() -> None:
    container = Container()
    container.add_concrete(_BoxA, provides=_IBox)
    container.add_concrete(_BoxB, provides=_IBox[T])

    resolved = container.resolve(_IBox[int])

    assert isinstance(resolved, _BoxB)


def test_open_concrete_registration_resolves_closed_generic_requests() -> None:
    container = Container()
    container.add_concrete(_Box, provides=_IBox)

    resolved = container.resolve(_IBox[str])

    assert isinstance(resolved, _Box)
    assert resolved.type is str


def test_closed_registration_wins_over_open_template() -> None:
    container = Container()
    container.add_concrete(_Box, provides=_IBox)
    container.add_concrete(_SpecialIntBox, provides=_IBox[int])

    int_box = container.resolve(_IBox[int])
    str_box = container.resolve(_IBox[str])

    assert isinstance(int_box, _SpecialIntBox)
    assert isinstance(str_box, _Box)
    assert str_box.type is str


def test_closed_generic_override_with_kw_only_dataclass_typevar_field_is_resolvable() -> None:
    container = Container()
    container.add_concrete(_KeywordBoxImpl, provides=_KeywordBox)
    container.add_concrete(_KeywordSpecialIntBox, provides=_KeywordBox[int])

    str_box = container.resolve(_KeywordBox[str])
    int_box = container.resolve(_KeywordBox[int])

    assert isinstance(str_box, _KeywordBoxImpl)
    assert str_box.type is str
    assert isinstance(int_box, _KeywordSpecialIntBox)
    assert int_box.type is int


def test_open_factory_registration_supports_type_argument_injection() -> None:
    container = Container()
    container.add_factory(_create_box, provides=_IBox)

    assert cast("Any", container.resolve(_IBox[int])).type is int
    assert cast("Any", container.resolve(_IBox[str])).type is str


def test_open_generator_registration_supports_type_argument_injection() -> None:
    container = Container()
    container.add_generator(_generate_box, provides=_IBox)

    resolved = container.resolve(_IBox[bytes])
    assert isinstance(resolved, _Box)
    assert resolved.type is bytes


def test_open_context_manager_registration_works_inside_container_context() -> None:
    container = Container()
    container.add_context_manager(_context_box, provides=_IBox)

    with container as resolver:
        resolved = resolver.resolve(_IBox[float])
        assert isinstance(resolved, _Box)
        assert resolved.type is float


@pytest.mark.asyncio
async def test_open_async_context_manager_registration_works_in_async_path() -> None:
    container = Container()
    container.add_context_manager(_async_context_box, provides=_IBox)

    async with container as resolver:
        resolved = await resolver.aresolve(_IBox[float])
        assert isinstance(resolved, _Box)
        assert resolved.type is float


def test_open_async_factory_raises_in_sync_resolution() -> None:
    container = Container()
    container.add_factory(_create_box_async, provides=_IBox)

    with pytest.raises(DIWireAsyncDependencyInSyncContextError, match="requires asynchronous"):
        container.resolve(_IBox[int])


class _Repo(Generic[T]):
    pass


@dataclass
class _GenericRepo(_Repo[T]):
    dependency_type: type[T]


@dataclass
class _ListRepo(_Repo[list[U]]):
    item_type: type[U]


def test_most_specific_open_template_wins_for_matching_request() -> None:
    container = Container()
    container.add_concrete(_GenericRepo, provides=_Repo)
    container.add_concrete(_ListRepo, provides=_Repo[list[U]])

    resolved_specific = container.resolve(_Repo[list[int]])
    resolved_fallback = container.resolve(_Repo[str])

    assert isinstance(resolved_specific, _ListRepo)
    assert resolved_specific.item_type is int
    assert isinstance(resolved_fallback, _GenericRepo)
    assert resolved_fallback.dependency_type is str


class _Model:
    pass


class _User(_Model):
    pass


M = TypeVar("M", bound=_Model)


class _ModelBox(Generic[M]):
    pass


@dataclass
class _DefaultModelBox(_ModelBox[M]):
    type: type[M]


def test_typevar_bound_is_validated_at_resolve_time() -> None:
    container = Container()
    container.add_concrete(_DefaultModelBox, provides=_ModelBox)

    valid = container.resolve(_ModelBox[_User])
    assert isinstance(valid, _DefaultModelBox)
    assert valid.type is _User

    invalid_key = cast("Any", _ModelBox)[str]
    with pytest.raises(DIWireInvalidGenericTypeArgumentError, match="bound"):
        container.resolve(invalid_key)


def test_injected_open_generic_uses_open_resolver_fallback() -> None:
    container = Container()
    container.add_concrete(_Box, provides=_IBox)

    @container.inject
    def handler(box: Injected[_IBox[str]]) -> str:
        resolved_box = cast("Any", box)
        return resolved_box.type.__name__

    assert cast("Any", handler)() == "str"


def test_container_context_replays_open_registrations_with_canonical_keys() -> None:
    context = ContainerContext()
    context.add_concrete(_BoxA, provides=_IBox)
    context.add_concrete(_BoxB, provides=_IBox[T])

    runtime = Container()
    context.set_current(runtime)

    resolved = runtime.resolve(_IBox[int])
    assert isinstance(resolved, _BoxB)


def test_open_singleton_cache_isolated_per_closed_dependency_key() -> None:
    container = Container()
    container.add_factory(_create_box, provides=_IBox, lifetime=Lifetime.SCOPED)

    int_first = container.resolve(_IBox[int])
    int_second = container.resolve(_IBox[int])
    str_box = container.resolve(_IBox[str])

    assert int_first is int_second
    assert cast("object", int_first) is not cast("object", str_box)


def test_open_scoped_cache_isolated_per_scope_and_closed_dependency_key() -> None:
    container = Container()
    container.add_factory(
        _create_box,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        container.resolve(_IBox[int])

    with container.enter_scope() as request_one:
        one_first = request_one.resolve(_IBox[int])
        one_second = request_one.resolve(_IBox[int])
        one_str = request_one.resolve(_IBox[str])

    with container.enter_scope() as request_two:
        two_first = request_two.resolve(_IBox[int])

    assert one_first is one_second
    assert cast("object", one_first) is not cast("object", one_str)
    assert cast("object", one_first) is not cast("object", two_first)


def test_open_scoped_cache_works_when_entering_action_scope_directly() -> None:
    container = Container()
    container.add_factory(
        _create_box,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.ACTION) as action_scope:
        first = action_scope.resolve(_IBox[int])
        second = action_scope.resolve(_IBox[int])
        other = action_scope.resolve(_IBox[str])

    with container.enter_scope(Scope.ACTION) as next_action_scope:
        next_scope_first = next_action_scope.resolve(_IBox[int])

    assert first is second
    assert cast("object", first) is not cast("object", other)
    assert cast("object", first) is not cast("object", next_scope_first)


def test_resolving_open_generic_without_type_arguments_remains_unregistered() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(_Box, provides=_IBox)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(_IBox)


def test_autoregister_skips_open_generic_dependencies_when_match_exists() -> None:
    container = Container()
    container.add_concrete(_Box, provides=_IBox)

    resolved = container.resolve(_IBox[int])

    assert isinstance(resolved, _Box)
    assert resolved.type is int


def test_closed_generic_injection_helpers_cover_non_injected_dependency_paths() -> None:
    container = Container()

    def _consumer(dep: str) -> None:
        _ = dep

    dependency = ProviderDependency(
        provides=str,
        parameter=inspect.signature(_consumer).parameters["dep"],
    )

    injected, remaining = container._resolve_closed_concrete_generic_injections(
        provides=_IBox[int],
        dependencies=[dependency],
    )

    assert injected == {}
    assert remaining == [dependency]
    assert container._closed_generic_typevar_map(provides=typing.Sequence) == {}
    assert container._closed_generic_typevar_map(
        provides=Annotated[_IBox[int], Component("primary")],
    ) == {T: int}
    assert container._closed_generic_typevar_map(provides=tuple[int]) == {}
    assert container._closed_generic_typevar_map(provides=inspect.Signature) == {}
    assert (
        container._resolve_closed_generic_injection_value(
            dependency_annotation=T,
            typevar_map={T: int},
        )
        is int
    )
    assert (
        container._resolve_closed_generic_injection_value(
            dependency_annotation=str,
            typevar_map={T: int},
        )
        is not int
    )
