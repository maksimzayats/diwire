from __future__ import annotations

import inspect
import threading
import typing
from collections.abc import AsyncGenerator, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated, Any, Generic, TypeVar, cast

import pytest
from typing_extensions import TypeVar as TypeVarExt

from diwire import (
    All,
    Component,
    Container,
    DependencyRegistrationPolicy,
    Injected,
    Lifetime,
    LockMode,
    Maybe,
    MissingPolicy,
    Provider,
    ResolverContext,
    Scope,
    resolver_context,
)
from diwire._internal.injection import INJECT_WRAPPER_MARKER
from diwire._internal.providers import (
    MATERIALIZED_PROVIDER_CALL_PLAN_KEY,
    MaterializedProviderCallPlan,
    ProviderDependency,
    ProviderSpec,
)
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireInvalidRegistrationError,
    DIWireScopeMismatchError,
)

T = TypeVar("T")
U = TypeVar("U")
DefaultT = TypeVarExt("DefaultT", default=str)
AutoDefaultT = TypeVarExt("AutoDefaultT", default=str)


class _IBox(Generic[T]):
    pass


@dataclass
class _DefaultBox(Generic[DefaultT]):
    type: type[DefaultT]


@dataclass
class _UsesDefaultBox:
    box: _DefaultBox


class _AutoOpen(Generic[AutoDefaultT]):
    def __init__(self, source: str = "concrete") -> None:
        self.source = source


@dataclass
class _UsesAutoOpen:
    dep: _AutoOpen


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


@dataclass
class _NoArgBox(_IBox[T]):
    pass


class _SpecialIntBox(_IBox[int]):
    def __init__(self) -> None:
        self.type = int


def _create_box(type_arg: type[T]) -> _IBox[T]:
    return _Box(type=type_arg)


def _create_default_box(type_arg: type[DefaultT]) -> _DefaultBox[DefaultT]:
    return _DefaultBox(type=type_arg)


def _create_auto_open(type_arg: type[AutoDefaultT]) -> _AutoOpen[AutoDefaultT]:
    return _AutoOpen(source=f"factory-{type_arg.__name__}")


def _create_box_positional_only(type_arg: type[T], /) -> _IBox[T]:
    return _Box(type=type_arg)


def _create_box_keyword_only(*, type_arg: type[T]) -> _IBox[T]:
    return _Box(type=type_arg)


class _CallableBoxFactory:
    def __call__(self, type_arg: type[T]) -> _IBox[T]:
        return _Box(type=type_arg)


_CALLABLE_BOX_FACTORY = _CallableBoxFactory()


async def _create_box_async(type_arg: type[T]) -> _IBox[T]:
    return _Box(type=type_arg)


def _generate_box(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
    try:
        yield _Box(type=type_arg)
    finally:
        pass


@contextmanager
def _context_box(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
    yield _Box(type=type_arg)


@asynccontextmanager
async def _async_context_box(type_arg: type[T]) -> AsyncGenerator[_IBox[T], None]:
    yield _Box(type=type_arg)


def test_open_key_canonicalization_allows_latest_override_for_equivalent_keys() -> None:
    container = Container()
    container.add(_BoxA, provides=_IBox)
    container.add(_BoxB, provides=_IBox[T])

    resolved = container.resolve(_IBox[int])

    assert isinstance(resolved, _BoxB)


def test_open_concrete_registration_resolves_closed_generic_requests() -> None:
    container = Container()
    container.add(_Box, provides=_IBox)

    resolved = container.resolve(_IBox[str])

    assert isinstance(resolved, _Box)
    assert resolved.type is str
    materialized = container._providers_registrations.find_by_type(_IBox[str])
    assert materialized is not None
    assert materialized.factory is not None


def test_open_concrete_registration_resolves_non_component_annotated_closed_key() -> None:
    container = Container()
    container.add(_Box, provides=_IBox)

    resolved = container.resolve(Annotated[_IBox[int], "meta"])

    assert isinstance(resolved, _Box)
    assert resolved.type is int


def test_closed_registration_wins_over_open_template() -> None:
    container = Container()
    container.add(_Box, provides=_IBox)
    container.add(_SpecialIntBox, provides=_IBox[int])

    int_box = container.resolve(_IBox[int])
    str_box = container.resolve(_IBox[str])

    assert isinstance(int_box, _SpecialIntBox)
    assert isinstance(str_box, _Box)
    assert str_box.type is str


def test_closed_generic_override_with_kw_only_dataclass_typevar_field_is_resolvable() -> None:
    container = Container()
    container.add(_KeywordBoxImpl, provides=_KeywordBox)
    container.add(_KeywordSpecialIntBox, provides=_KeywordBox[int])

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
    materialized = container._providers_registrations.find_by_type(_IBox[int])
    assert materialized is not None
    assert materialized.factory is not None


@pytest.mark.parametrize(
    "factory",
    [_create_box, _create_box_positional_only, _CALLABLE_BOX_FACTORY.__call__],
    ids=("function", "positional-only", "bound-method"),
)
def test_materialized_one_argument_factory_uses_exact_generated_direct_call(
    factory: Any,
) -> None:
    container = Container(
        lock_mode=LockMode.NONE,
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
        use_resolver_context=False,
    )
    container.add_factory(
        factory,
        provides=_IBox,
        lifetime=Lifetime.TRANSIENT,
    )
    container.compile()

    int_first = cast("Any", container.resolve(_IBox[int]))
    str_first = cast("Any", container.resolve(_IBox[str]))
    int_second = cast("Any", container.resolve(_IBox[int]))
    str_second = cast("Any", container.resolve(_IBox[str]))

    assert int_first.type is int
    assert str_first.type is str
    assert int_second.type is int
    assert str_second.type is str
    assert int_first is not int_second
    assert str_first is not str_second

    root_wrapper = cast("Any", container._root_resolver)
    base_resolver = root_wrapper._base_resolver
    for dependency, argument in ((_IBox[int], int), (_IBox[str], str)):
        materialized = container._providers_registrations.get_by_type(dependency)
        wrapper = materialized.factory
        assert wrapper is not None
        wrapper_metadata = cast("dict[Any, Any]", wrapper.__dict__)
        call_plan = wrapper_metadata[MATERIALIZED_PROVIDER_CALL_PLAN_KEY]
        assert call_plan == MaterializedProviderCallPlan(
            provider=factory,
            argument=argument,
        )
        assert cast("Any", wrapper()).type is argument

        slot_method = getattr(type(base_resolver), f"resolve_{materialized.slot}")
        slot_names = slot_method.__code__.co_names
        assert f"_materialized_provider_{materialized.slot}" in slot_names
        assert f"_materialized_argument_{materialized.slot}" in slot_names
        assert f"_provider_{materialized.slot}" not in slot_names
        assert slot_method.__globals__[f"_provider_{materialized.slot}"] is wrapper


def test_materialized_keyword_only_factory_keeps_wrapper_call() -> None:
    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(
        _create_box_keyword_only,
        provides=_IBox,
        lifetime=Lifetime.TRANSIENT,
    )

    first = cast("Any", container.resolve(_IBox[int]))
    second = cast("Any", container.resolve(_IBox[int]))

    assert first.type is int
    assert second.type is int
    materialized = container._providers_registrations.get_by_type(_IBox[int])
    wrapper = materialized.factory
    assert wrapper is not None
    assert MATERIALIZED_PROVIDER_CALL_PLAN_KEY not in wrapper.__dict__
    root_wrapper = cast("Any", container._root_resolver)
    slot_method = getattr(
        type(root_wrapper._base_resolver),
        f"resolve_{materialized.slot}",
    )
    assert f"_provider_{materialized.slot}" in slot_method.__code__.co_names


@pytest.mark.parametrize(
    ("prebuilt_args", "prebuilt_kwargs"),
    [((int, str), {}), ((int,), {"other": str}), ((), {"type_arg": int})],
    ids=("multiple-positional", "positional-and-keyword", "keyword-only"),
)
def test_prebound_materialized_non_one_positional_shapes_have_no_direct_call_plan(
    prebuilt_args: tuple[Any, ...],
    prebuilt_kwargs: dict[str, Any],
) -> None:
    container = Container()

    def _capture(*args: Any, **kwargs: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return args, kwargs

    wrapper = container._build_prebound_materialized_wrapper(
        provider=_capture,
        prebuilt_args=prebuilt_args,
        prebuilt_kwargs=prebuilt_kwargs,
    )

    assert wrapper() == (prebuilt_args, prebuilt_kwargs)
    assert MATERIALIZED_PROVIDER_CALL_PLAN_KEY not in wrapper.__dict__


def test_open_factory_materialized_wrapper_uses_bind_partial_fallback_for_positional_only() -> None:
    container = Container()
    container.add_factory(_create_box_positional_only, provides=_IBox)

    resolved = container.resolve(_IBox[int])

    assert isinstance(resolved, _Box)
    assert resolved.type is int
    materialized = container._providers_registrations.find_by_type(_IBox[int])
    assert materialized is not None
    assert materialized.factory is not None


def test_open_generator_registration_supports_type_argument_injection() -> None:
    container = Container()
    container.add_generator(_generate_box, provides=_IBox)

    resolved = container.resolve(_IBox[bytes])
    assert isinstance(resolved, _Box)
    assert resolved.type is bytes
    materialized = container._providers_registrations.find_by_type(_IBox[bytes])
    assert materialized is not None
    assert materialized.generator is not None


def test_open_context_manager_registration_works_inside_resolver_context() -> None:
    container = Container()
    container.add_context_manager(_context_box, provides=_IBox)

    with container as resolver:
        resolved = resolver.resolve(_IBox[float])
        assert isinstance(resolved, _Box)
        assert resolved.type is float
    materialized = container._providers_registrations.find_by_type(_IBox[float])
    assert materialized is not None
    assert materialized.context_manager is not None


def test_open_generic_scope_resolver_close_runs_cleanup_via_wrapper_delegate() -> None:
    events: list[str] = []

    def _tracked_open_generator(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
        events.append(f"enter-{type_arg.__name__}")
        try:
            yield _Box(type=type_arg)
        finally:
            events.append(f"exit-{type_arg.__name__}")

    container = Container()
    container.add_generator(
        _tracked_open_generator,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    request_scope = container.enter_scope()

    resolved = request_scope.resolve(_IBox[int])
    assert isinstance(resolved, _Box)
    assert resolved.type is int

    request_scope.close()
    assert events == ["enter-int", "exit-int"]


def test_open_scoped_cleanup_is_owned_by_overlapping_scope_and_runs_lifo() -> None:
    closed: list[object] = []

    def _tracked_open_generator(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
        box = _Box(type=type_arg)
        try:
            yield box
        finally:
            closed.append(box)

    container = Container()
    container.add_generator(
        _tracked_open_generator,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    first_scope = container.enter_scope()
    second_scope = container.enter_scope()
    first_int = first_scope.resolve(_IBox[int])
    first_str = first_scope.resolve(_IBox[str])
    second_int = second_scope.resolve(_IBox[int])
    second_str = second_scope.resolve(_IBox[str])

    assert first_scope.resolve(_IBox[int]) is first_int
    assert second_scope.resolve(_IBox[int]) is second_int
    assert cast("object", first_int) is not cast("object", second_int)
    assert cast("object", first_str) is not cast("object", second_str)

    first_scope.close()

    assert closed == [first_str, first_int]
    assert second_scope.resolve(_IBox[int]) is second_int

    second_scope.close()

    assert closed == [first_str, first_int, second_str, second_int]


def test_direct_action_scope_owns_implicit_request_open_cleanup_and_forwards_error() -> None:
    events: list[str] = []

    @contextmanager
    def _tracked_open_context(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
        events.append(f"enter-{type_arg.__name__}")
        try:
            yield _Box(type=type_arg)
        except ValueError as error:
            events.append(f"error-{type_arg.__name__}-{error}")
            raise
        finally:
            events.append(f"exit-{type_arg.__name__}")

    container = Container()
    container.add_context_manager(
        _tracked_open_context,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(ValueError, match="body boom"):
        with container.enter_scope(Scope.ACTION) as action_scope:
            action_scope.resolve(_IBox[int])
            action_scope.resolve(_IBox[str])
            raise ValueError("body boom")

    assert events == [
        "enter-int",
        "enter-str",
        "error-str-body boom",
        "exit-str",
        "error-int-body boom",
        "exit-int",
    ]


def test_nested_action_close_keeps_request_owned_open_resource_alive() -> None:
    events: list[str] = []

    @contextmanager
    def _tracked_open_context(type_arg: type[T]) -> Generator[_IBox[T], None, None]:
        events.append(f"enter-{type_arg.__name__}")
        try:
            yield _Box(type=type_arg)
        finally:
            events.append(f"exit-{type_arg.__name__}")

    container = Container()
    container.add_context_manager(
        _tracked_open_context,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with request_scope.enter_scope(Scope.ACTION) as action_scope:
            resolved = action_scope.resolve(_IBox[int])

        assert events == ["enter-int"]
        assert request_scope.resolve(_IBox[int]) is resolved

    assert events == ["enter-int", "exit-int"]


@pytest.mark.asyncio
async def test_open_async_context_manager_registration_works_in_async_path() -> None:
    container = Container()
    container.add_context_manager(_async_context_box, provides=_IBox)

    async with container as resolver:
        resolved = await resolver.aresolve(_IBox[float])
        assert isinstance(resolved, _Box)
        assert resolved.type is float
    materialized = container._providers_registrations.find_by_type(_IBox[float])
    assert materialized is not None
    assert materialized.context_manager is not None


@pytest.mark.asyncio
async def test_open_async_factory_materializes_closed_key() -> None:
    container = Container()
    container.add_factory(_create_box_async, provides=_IBox)

    resolved = await container.aresolve(_IBox[int])

    assert isinstance(resolved, _Box)
    assert resolved.type is int
    materialized = container._providers_registrations.find_by_type(_IBox[int])
    assert materialized is not None
    assert materialized.factory is not None


@pytest.mark.asyncio
async def test_open_generic_scope_resolver_aclose_runs_cleanup_via_wrapper_delegate() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def _tracked_open_async_context(type_arg: type[T]) -> AsyncGenerator[_IBox[T], None]:
        events.append(f"enter-{type_arg.__name__}")
        try:
            yield _Box(type=type_arg)
        finally:
            events.append(f"exit-{type_arg.__name__}")

    container = Container()
    container.add_context_manager(
        _tracked_open_async_context,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    request_scope = container.enter_scope()

    resolved = await request_scope.aresolve(_IBox[int])
    assert isinstance(resolved, _Box)
    assert resolved.type is int

    await request_scope.aclose()
    assert events == ["enter-int", "exit-int"]


@pytest.mark.asyncio
async def test_direct_action_scope_async_cleanup_owns_implicit_request_and_forwards_error() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def _tracked_open_context(
        type_arg: type[T],
    ) -> AsyncGenerator[_IBox[T], None]:
        events.append(f"enter-{type_arg.__name__}")
        try:
            yield _Box(type=type_arg)
        except ValueError as error:
            events.append(f"error-{type_arg.__name__}-{error}")
            raise
        finally:
            events.append(f"exit-{type_arg.__name__}")

    container = Container()
    container.add_context_manager(
        _tracked_open_context,
        provides=_IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(ValueError, match="async body boom"):
        async with container.enter_scope(Scope.ACTION) as action_scope:
            await action_scope.aresolve(_IBox[int])
            await action_scope.aresolve(_IBox[str])
            raise ValueError("async body boom")

    assert events == [
        "enter-int",
        "enter-str",
        "error-str-async body boom",
        "exit-str",
        "error-int-async body boom",
        "exit-int",
    ]


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
    container.add(_GenericRepo, provides=_Repo)
    container.add(_ListRepo, provides=_Repo[list[U]])

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
    container.add(_DefaultModelBox, provides=_ModelBox)

    valid = container.resolve(_ModelBox[_User])
    assert isinstance(valid, _DefaultModelBox)
    assert valid.type is _User

    invalid_key = cast("Any", _ModelBox)[str]
    with pytest.raises(DIWireInvalidGenericTypeArgumentError, match="bound"):
        container.resolve(invalid_key)
    assert container._providers_registrations.find_by_type(invalid_key) is None


def test_materialized_closed_key_is_purged_before_registration_mutation() -> None:
    container = Container(lock_mode=LockMode.NONE)
    container.add_instance("keep", provides=str)
    container.add(_BoxA, provides=_IBox)

    first = container.resolve(_IBox[int])
    assert isinstance(first, _BoxA)
    assert isinstance(container.resolve(_IBox[int]), _BoxA)
    assert container._providers_registrations.find_by_type(_IBox[int]) is not None

    container.add(_BoxB, provides=_IBox)
    assert container._providers_registrations.find_by_type(_IBox[int]) is None
    assert container.resolve(str) == "keep"

    second = container.resolve(_IBox[int])
    assert isinstance(second, _BoxB)
    assert isinstance(container.resolve(_IBox[int]), _BoxB)


def test_generated_direct_scoped_provider_failure_retries_before_cache_publication() -> None:
    call_count = 0
    failure = RuntimeError("materialized provider failure")

    def _flaky_factory(type_arg: type[T]) -> _IBox[T]:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise failure
        return _Box(type=type_arg)

    container = Container(
        lock_mode=LockMode.NONE,
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
        use_resolver_context=False,
    )
    container.add_factory(
        _flaky_factory,
        provides=_IBox,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as materializing_scope:
        initial = cast("Any", materializing_scope.resolve(_IBox[int]))
    assert initial.type is int
    assert call_count == 1

    with container.enter_scope(Scope.REQUEST) as direct_scope:
        materialized = container._providers_registrations.get_by_type(_IBox[int])
        slot_method = getattr(
            type(cast("Any", direct_scope)._base_resolver),
            f"resolve_{materialized.slot}",
        )
        assert f"_materialized_provider_{materialized.slot}" in slot_method.__code__.co_names

        with pytest.raises(RuntimeError) as raised:
            direct_scope.resolve(_IBox[int])
        assert raised.value is failure

        resolved = direct_scope.resolve(_IBox[int])
        cached = direct_scope.resolve(_IBox[int])

    assert cast("Any", resolved).type is int
    assert cached is resolved
    assert call_count == 3


def test_materialized_open_concrete_without_type_argument_dependencies_stays_concrete() -> None:
    container = Container()
    container.add(_NoArgBox, provides=_IBox)

    resolved = container.resolve(_IBox[int])

    assert isinstance(resolved, _NoArgBox)
    materialized = container._providers_registrations.find_by_type(_IBox[int])
    assert materialized is not None
    assert materialized.concrete_type is _NoArgBox


def test_open_generic_dispatch_cache_is_used_after_first_materialized_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()
    container.add_factory(_create_box, provides=_IBox)

    registry = container._open_generic_registry
    find_best_match_call_count = 0
    original_find_best_match = registry.find_best_match

    def _counting_find_best_match(dependency: Any) -> Any:
        nonlocal find_best_match_call_count
        find_best_match_call_count += 1
        return original_find_best_match(dependency)

    monkeypatch.setattr(registry, "find_best_match", _counting_find_best_match)

    first = container.resolve(_IBox[int])
    second = container.resolve(_IBox[int])

    assert isinstance(first, _Box)
    assert isinstance(second, _Box)
    assert find_best_match_call_count == 1


def test_materialized_open_generic_preserves_inject_wrapper_marker() -> None:
    container = Container()

    def _inject_wrapped_factory(type_arg: type[T]) -> _IBox[T]:
        return _Box(type=type_arg)

    wrapped_factory = resolver_context.inject(_inject_wrapped_factory)
    container.add_factory(wrapped_factory, provides=_IBox)

    resolved = container.resolve(_IBox[int])

    assert isinstance(resolved, _Box)
    materialized = container._providers_registrations.find_by_type(_IBox[int])
    assert materialized is not None
    assert materialized.factory is not None
    assert bool(getattr(materialized.factory, INJECT_WRAPPER_MARKER, False))


def test_unresolved_nested_typevar_error_does_not_materialize_invalid_closed_key() -> None:
    container = Container()

    def _invalid_factory(type_arg: type[T], value: list[U]) -> _IBox[T]:
        _ = value
        return _Box(type=type_arg)

    container.add_factory(_invalid_factory, provides=_IBox)

    with pytest.raises(DIWireInvalidGenericTypeArgumentError, match="unresolved TypeVars"):
        container.resolve(_IBox[int])
    assert container._providers_registrations.find_by_type(_IBox[int]) is None


def test_materialization_callback_noops_when_closed_dependency_is_already_registered() -> None:
    container = Container()
    container.add_instance(1, provides=int)

    dummy_match = SimpleNamespace(spec=object(), typevar_map={})
    container._materialize_closed_open_generic_spec(int, dummy_match)

    assert container.resolve(int) == 1


def test_materialization_callback_skips_invalid_generic_argument_binding_without_typevar() -> None:
    container = Container()

    def _factory(dummy: int) -> _IBox[int]:
        _ = dummy
        return _Box(type=int)

    parameter = inspect.signature(_factory).parameters["dummy"]
    binding = SimpleNamespace(
        kind="generic_argument",
        typevar=None,
        dependency=ProviderDependency(provides=int, parameter=parameter),
    )
    spec = SimpleNamespace(
        bindings=(binding,),
        provider_kind="factory",
        provider=_factory,
        provider_is_inject_wrapper=False,
        lifetime=Lifetime.SCOPED,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        lock_mode=LockMode.NONE,
    )
    match = SimpleNamespace(spec=spec, typevar_map={})

    container._materialize_closed_open_generic_spec(_IBox[int], match)
    assert container._providers_registrations.find_by_type(_IBox[int]) is None


def test_materialization_callback_skips_missing_typevar_argument_value() -> None:
    container = Container()

    def _factory(type_arg: type[T]) -> _IBox[T]:
        return _Box(type=type_arg)

    parameter = inspect.signature(_factory).parameters["type_arg"]
    typevar = TypeVar("typevar")
    binding = SimpleNamespace(
        kind="generic_argument",
        typevar=typevar,
        dependency=ProviderDependency(provides=type[T], parameter=parameter),
    )
    spec = SimpleNamespace(
        bindings=(binding,),
        provider_kind="factory",
        provider=_factory,
        provider_is_inject_wrapper=False,
        lifetime=Lifetime.SCOPED,
        scope=Scope.APP,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
        lock_mode=LockMode.NONE,
    )
    match = SimpleNamespace(spec=spec, typevar_map={})

    container._materialize_closed_open_generic_spec(_IBox[int], match)
    assert container._providers_registrations.find_by_type(_IBox[int]) is None


def test_injected_open_generic_uses_open_resolver_fallback() -> None:
    container = Container()
    container.add(_Box, provides=_IBox)

    @resolver_context.inject
    def handler(box: Injected[_IBox[str]]) -> str:
        resolved_box = cast("Any", box)
        return resolved_box.type.__name__

    assert cast("Any", handler)() == "str"


def test_resolver_context_fallback_uses_latest_canonical_open_key() -> None:
    context = ResolverContext()
    runtime = Container(resolver_context=context)
    runtime.add(_BoxA, provides=_IBox)
    runtime.add(_BoxB, provides=_IBox[T])

    @context.inject
    def handler(box: Injected[_IBox[int]]) -> _IBox[int]:
        return box

    resolved = cast("Any", handler)()
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

    assert request_one is not request_two
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

    assert action_scope is not next_action_scope
    assert first is second
    assert cast("object", first) is not cast("object", other)
    assert cast("object", first) is not cast("object", next_scope_first)


def test_resolving_open_generic_without_type_arguments_remains_unregistered() -> None:
    container = Container()
    container.add(_Box, provides=_IBox)

    with pytest.raises(DIWireDependencyNotRegisteredError):
        container.resolve(_IBox)


def test_resolving_open_generic_without_type_arguments_uses_typevar_defaults() -> None:
    container = Container()
    container.add_factory(_create_default_box, provides=_DefaultBox)

    default_resolved = container.resolve(_DefaultBox)
    explicit_resolved = container.resolve(_DefaultBox[int])

    assert isinstance(default_resolved, _DefaultBox)
    assert default_resolved.type is str
    assert isinstance(explicit_resolved, _DefaultBox)
    assert explicit_resolved.type is int
    assert container._providers_registrations.find_by_type(_DefaultBox[str]) is not None


def test_open_generic_default_typevar_dependency_resolves_for_registered_provider() -> None:
    container = Container()
    container.add_factory(_create_default_box, provides=_DefaultBox)
    container.add(_UsesDefaultBox)

    resolved = container.resolve(_UsesDefaultBox)

    assert isinstance(resolved, _UsesDefaultBox)
    assert isinstance(resolved.box, _DefaultBox)
    assert resolved.box.type is str


def test_open_generic_default_typevar_dependency_resolves_for_autoregistered_provider() -> None:
    container = Container()
    container.add_factory(_create_default_box, provides=_DefaultBox)

    resolved = container.resolve(_UsesDefaultBox)

    assert isinstance(resolved, _UsesDefaultBox)
    assert isinstance(resolved.box, _DefaultBox)
    assert resolved.box.type is str


def test_open_generic_dependency_autoregistration_does_not_override_open_registration() -> None:
    container = Container()
    container.add_factory(_create_auto_open, provides=_AutoOpen)

    resolved = container.resolve(_UsesAutoOpen)

    assert isinstance(resolved, _UsesAutoOpen)
    assert isinstance(resolved.dep, _AutoOpen)
    assert resolved.dep.source == "factory-str"


def test_open_generic_materialization_dependency_key_handles_markers() -> None:
    container = Container()

    assert container._open_generic_materialization_dependency_key(Maybe[_IBox[int]]) == _IBox[int]
    assert (
        container._open_generic_materialization_dependency_key(Provider[_IBox[int]]) == _IBox[int]
    )
    assert container._open_generic_materialization_dependency_key(All[_IBox[int]]) is None


def test_materialize_registered_open_generic_dependencies_covers_no_match_and_all_marker() -> None:
    container = Container()
    container.add_factory(_create_box, provides=_IBox)

    @dataclass
    class _UsesAllBox:
        items: All[_IBox[Any]]

    @dataclass
    class _UsesUnmatchedDependency:
        value: _DefaultBox

    container.add(
        _UsesAllBox,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )
    container.add(
        _UsesUnmatchedDependency,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    container._materialize_registered_open_generic_dependencies()

    assert container._providers_registrations.find_by_type(_DefaultBox) is None


def test_materialize_registered_open_generic_dependencies_materializes_and_rechecks() -> None:
    container = Container()
    container.add_factory(_create_default_box, provides=_DefaultBox)
    container.add(
        _UsesDefaultBox,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    assert container._providers_registrations.find_by_type(_DefaultBox) is None

    container._materialize_registered_open_generic_dependencies()

    assert container._providers_registrations.find_by_type(_DefaultBox) is not None


def test_materialize_registered_open_generic_dependencies_reiterates_after_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _NeedsStr:
        value: str
        mirror: str

    container.add(
        _NeedsStr,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    materialization_marker = object()
    materialization_calls = 0

    monkeypatch.setattr(container._open_generic_registry, "has_specs", lambda: True)

    def _find_best_match(dependency: Any) -> Any:
        if dependency is str and container._providers_registrations.find_by_type(str) is None:
            return materialization_marker
        return None

    monkeypatch.setattr(container._open_generic_registry, "find_best_match", _find_best_match)

    def _materialize(dependency: Any, match: Any) -> None:
        nonlocal materialization_calls
        materialization_calls += 1
        assert dependency is str
        assert match is materialization_marker
        container.add_instance("materialized", provides=str)

    monkeypatch.setattr(container, "_materialize_closed_open_generic_spec", _materialize)

    container._materialize_registered_open_generic_dependencies()

    assert materialization_calls == 1
    assert container._providers_registrations.find_by_type(str) is not None


def test_materialize_registered_open_generic_dependencies_raises_on_non_converging_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _NeedsDependency:
        value: str

    container.add(
        _NeedsDependency,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    materialization_marker = object()
    dependency_counter = 0
    materialized_dependencies: list[Any] = []

    monkeypatch.setattr(container, "_OPEN_GENERIC_MATERIALIZATION_MAX_ITERATIONS", 5, raising=False)
    monkeypatch.setattr(container._open_generic_registry, "has_specs", lambda: True)
    monkeypatch.setattr(container, "_purge_runtime_materialized_closed_specs", lambda: None)
    monkeypatch.setattr(
        container._open_generic_registry,
        "find_best_match",
        lambda _dependency: materialization_marker,
    )

    def _dependency_key(_dependency: Any) -> Any:
        nonlocal dependency_counter
        dependency_counter += 1
        dependency = cast("Any", type(f"_SyntheticDependency{dependency_counter}", (), {}))
        materialized_dependencies.append(dependency)
        return dependency

    monkeypatch.setattr(container, "_open_generic_materialization_dependency_key", _dependency_key)

    def _materialize(dependency: Any, match: Any) -> None:
        assert match is materialization_marker
        container.add_instance(object(), provides=dependency)
        container._runtime_materialized_closed_keys.add(dependency)

    monkeypatch.setattr(container, "_materialize_closed_open_generic_spec", _materialize)

    with pytest.raises(DIWireInvalidRegistrationError, match="did not converge") as error_info:
        container._materialize_registered_open_generic_dependencies()

    message = str(error_info.value)
    assert "_open_generic_materialization_dependency_key" in message
    assert "_materialize_closed_open_generic_spec" in message
    assert "_providers_registrations" in message
    assert "_open_generic_registry" in message
    for dependency in materialized_dependencies:
        assert container._providers_registrations.find_by_type(dependency) is None
        assert dependency not in container._runtime_materialized_closed_keys


def test_materialize_registered_open_generic_dependencies_no_growth_rechecks_remaining_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _NeedsTwoDependencies:
        first: str
        second: int

    container.add(
        _NeedsTwoDependencies,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    materialization_marker = object()
    materialized_dependencies: list[Any] = []

    monkeypatch.setattr(container._open_generic_registry, "has_specs", lambda: True)
    monkeypatch.setattr(
        container._open_generic_registry,
        "find_best_match",
        lambda _dependency: materialization_marker,
    )

    def _materialize(dependency: Any, match: Any) -> None:
        assert match is materialization_marker
        materialized_dependencies.append(dependency)

    monkeypatch.setattr(container, "_materialize_closed_open_generic_spec", _materialize)

    container._materialize_registered_open_generic_dependencies()

    assert materialized_dependencies == [str, int]


def test_materialize_registered_open_generic_dependencies_raises_on_repeated_growth_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _NeedsDependency:
        value: str

    container.add(
        _NeedsDependency,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    provider_spec = next(iter(container._providers_registrations.values()))
    values_call_counter = 0
    values_len_pattern = (1, 1, 1, 2, 1)
    materialization_marker = object()
    materialized_dependencies: list[Any] = []

    def _values() -> list[Any]:
        nonlocal values_call_counter
        values_len = values_len_pattern[values_call_counter % len(values_len_pattern)]
        values_call_counter += 1
        if values_len == 1:
            return [provider_spec]
        return [provider_spec, provider_spec]

    monkeypatch.setattr(container._providers_registrations, "values", _values)
    monkeypatch.setattr(container._open_generic_registry, "has_specs", lambda: True)
    monkeypatch.setattr(container, "_purge_runtime_materialized_closed_specs", lambda: None)
    monkeypatch.setattr(
        container._open_generic_registry,
        "find_best_match",
        lambda _dependency: materialization_marker,
    )

    class _SyntheticDependency:
        def __repr__(self) -> str:
            return "_SyntheticDependency"

    def _dependency_key(_dependency: Any) -> Any:
        dependency = _SyntheticDependency()
        materialized_dependencies.append(dependency)
        return dependency

    monkeypatch.setattr(container, "_open_generic_materialization_dependency_key", _dependency_key)

    def _materialize(dependency: Any, _match: Any) -> None:
        materialized_spec = ProviderSpec(
            provides=dependency,
            instance=object(),
            dependencies=[],
            is_async=False,
            is_any_dependency_async=False,
            needs_cleanup=False,
            lock_mode="auto",
            scope=container._root_scope,
        )
        container._providers_registrations._registrations_by_type[dependency] = materialized_spec
        container._providers_registrations._registrations_by_slot[materialized_spec.slot] = (
            materialized_spec
        )
        container._runtime_materialized_closed_keys.add(dependency)

    monkeypatch.setattr(container, "_materialize_closed_open_generic_spec", _materialize)

    with pytest.raises(DIWireInvalidRegistrationError, match="repeated_iteration_state"):
        container._materialize_registered_open_generic_dependencies()

    assert container._providers_registrations.find_by_type(_NeedsDependency) is not None
    for dependency in materialized_dependencies:
        assert container._providers_registrations.find_by_type(dependency) is None
        assert dependency not in container._runtime_materialized_closed_keys


def test_materialize_registered_open_generic_dependencies_deduplicates_tracked_growth_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _NeedsDependency:
        value: str

    container.add(
        _NeedsDependency,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    provider_spec = next(iter(container._providers_registrations.values()))
    values_call_counter = 0
    values_len_pattern = (1, 1, 1, 2, 1)
    materialization_marker = object()
    rollback_calls: list[tuple[list[Any], list[Any]]] = []
    original_rollback = container._rollback_open_generic_materialization

    def _values() -> list[Any]:
        nonlocal values_call_counter
        values_len = values_len_pattern[values_call_counter % len(values_len_pattern)]
        values_call_counter += 1
        if values_len == 1:
            return [provider_spec]
        return [provider_spec, provider_spec]

    def _rollback(
        *, materialized_registration_keys: list[Any], materialized_closed_keys: list[Any]
    ) -> None:
        rollback_calls.append(
            (list(materialized_registration_keys), list(materialized_closed_keys))
        )
        original_rollback(
            materialized_registration_keys=materialized_registration_keys,
            materialized_closed_keys=materialized_closed_keys,
        )

    monkeypatch.setattr(container._providers_registrations, "values", _values)
    monkeypatch.setattr(container._open_generic_registry, "has_specs", lambda: True)
    monkeypatch.setattr(
        container._open_generic_registry,
        "find_best_match",
        lambda _dependency: materialization_marker,
    )
    monkeypatch.setattr(
        container, "_open_generic_materialization_dependency_key", lambda _dependency: str
    )
    monkeypatch.setattr(container, "_materialize_closed_open_generic_spec", lambda *_args: None)
    monkeypatch.setattr(container, "_rollback_open_generic_materialization", _rollback)

    with pytest.raises(DIWireInvalidRegistrationError, match="repeated_iteration_state"):
        container._materialize_registered_open_generic_dependencies()

    assert rollback_calls == [([str], [])]


def test_rollback_open_generic_materialization_is_noop_when_nothing_tracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _Service:
        value: str

    container.add(_Service, dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)
    original_registrations = container._providers_registrations
    invalidate_calls = 0

    def _invalidate() -> None:
        nonlocal invalidate_calls
        invalidate_calls += 1

    monkeypatch.setattr(container, "_invalidate_compilation", _invalidate)

    container._rollback_open_generic_materialization(
        materialized_registration_keys=[],
        materialized_closed_keys=[],
    )

    assert container._providers_registrations is original_registrations
    assert invalidate_calls == 0


def test_rollback_open_generic_materialization_discards_closed_keys_without_rebuilding_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()

    @dataclass
    class _Service:
        value: str

    container.add(_Service, dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)
    original_registrations = container._providers_registrations
    materialized_key = object()
    container._runtime_materialized_closed_keys.add(materialized_key)
    invalidate_calls = 0

    def _invalidate() -> None:
        nonlocal invalidate_calls
        invalidate_calls += 1

    monkeypatch.setattr(container, "_invalidate_compilation", _invalidate)

    container._rollback_open_generic_materialization(
        materialized_registration_keys=[],
        materialized_closed_keys=[materialized_key],
    )

    assert container._providers_registrations is original_registrations
    assert materialized_key not in container._runtime_materialized_closed_keys
    assert invalidate_calls == 1


def test_autoregister_skips_open_generic_dependencies_when_match_exists() -> None:
    container = Container()
    container.add(_Box, provides=_IBox)

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


def test_runtime_materialization_serializes_provider_registration_add_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(
        _create_box,
        provides=_IBox,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
    )
    container.compile()

    active_add_calls = 0
    observed_overlap = False
    active_add_calls_lock = threading.Lock()
    start_event = threading.Event()
    original_add = container._providers_registrations.add

    def _tracked_add(spec: Any) -> None:
        nonlocal active_add_calls, observed_overlap
        start_event.wait(timeout=5)
        with active_add_calls_lock:
            active_add_calls += 1
            if active_add_calls > 1:
                observed_overlap = True
        try:
            original_add(spec)
        finally:
            with active_add_calls_lock:
                active_add_calls -= 1

    monkeypatch.setattr(container._providers_registrations, "add", _tracked_add)

    dependencies = [type(f"_ConcurrentType{index}", (), {}) for index in range(32)]

    def _resolve_dependency(dependency: type[Any]) -> Any:
        return container.resolve(_IBox[dependency])

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_resolve_dependency, dependency) for dependency in dependencies]
        start_event.set()
        for future in futures:
            future.result()

    assert observed_overlap is False
    for dependency in dependencies:
        assert container._providers_registrations.find_by_type(_IBox[dependency]) is not None
        assert cast("Any", container.resolve(_IBox[dependency])).type is dependency


def test_compile_is_safe_during_concurrent_runtime_materialization() -> None:
    container = Container()
    container.add_factory(
        _create_box,
        provides=_IBox,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.APP,
    )
    container.compile()

    failures: list[BaseException] = []
    failures_lock = threading.Lock()
    dependencies = [type(f"_CompileRaceType{index}", (), {}) for index in range(48)]

    def _record_failure(error: BaseException) -> None:
        with failures_lock:
            failures.append(error)

    def _resolve_dependency(dependency: type[Any]) -> None:
        try:
            container.resolve(_IBox[dependency])
        except BaseException as error:
            _record_failure(error)

    def _compile_many_times() -> None:
        try:
            for _ in range(200):
                container.compile()
        except BaseException as error:
            _record_failure(error)

    with ThreadPoolExecutor(max_workers=20) as executor:
        compile_future = executor.submit(_compile_many_times)
        resolve_futures = [
            executor.submit(_resolve_dependency, dependency) for dependency in dependencies
        ]
        compile_future.result()
        for resolve_future in resolve_futures:
            resolve_future.result()

    assert failures == []
