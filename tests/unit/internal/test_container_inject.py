from __future__ import annotations

import importlib
import inspect
from collections.abc import Generator
from typing import Annotated, Any, Generic, NamedTuple, TypeVar, cast

import pytest

import diwire._internal.injection as injection_module
from diwire import (
    Component,
    Container,
    DependencyRegistrationPolicy,
    FromContext,
    Injected,
    Lifetime,
    Scope,
    resolver_context,
)
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireInvalidRegistrationError,
    DIWireScopeMismatchError,
)


class _InjectedSyncDependency:
    def __init__(self, value: str) -> None:
        self.value = value


class _InjectedAsyncDependency:
    def __init__(self, value: str) -> None:
        self.value = value


class _RequestDependency:
    pass


class _RequestScopedResource:
    pass


class _RequestConsumer:
    def __init__(self, dependency: _RequestDependency) -> None:
        self.dependency = dependency


class _AutoLeaf:
    pass


class _AutoBranch:
    def __init__(self, leaf: _AutoLeaf) -> None:
        self.leaf = leaf


class _AutoRoot:
    def __init__(self, branch: _AutoBranch) -> None:
        self.branch = branch


def _load_pydantic_settings_base() -> type[Any] | None:
    try:
        module = importlib.import_module("pydantic_settings")
    except ImportError:
        return None
    base_settings = getattr(module, "BaseSettings", None)
    if isinstance(base_settings, type):
        return cast("type[Any]", base_settings)
    return None


_pydantic_settings_base = _load_pydantic_settings_base()
_InjectedSettingsBase: type[Any]
if _pydantic_settings_base is None:

    class _MissingInjectedSettingsBase:
        pass

    _InjectedSettingsBase = _MissingInjectedSettingsBase
else:
    _InjectedSettingsBase = _pydantic_settings_base


class _InjectedSettings(_InjectedSettingsBase):
    value: str = "settings"


class _ResolverStub:
    def __init__(self, value: object) -> None:
        self.value = value
        self.sync_calls = 0
        self.async_calls = 0

    def resolve(self, dependency: object) -> object:
        self.sync_calls += 1
        return self.value

    async def aresolve(self, dependency: object) -> object:
        self.async_calls += 1
        return self.value


class _Database:
    pass


PrimaryDatabase = Annotated[_Database, Component("primary")]


class _PrimaryDatabase(_Database):
    pass


class _AutoregisterCase(NamedTuple):
    default_enabled: bool
    expect_registered: bool


class _NestedInnerService:
    def __init__(self, dependency: _RequestDependency) -> None:
        self.dependency = dependency


class _NestedOuterService:
    def __init__(self, inner: _NestedInnerService, dependency: _RequestDependency) -> None:
        self.inner = inner
        self.dependency = dependency


G = TypeVar("G")


class _InjectedOpenBox(Generic[G]):
    pass


class _InjectedOpenBoxImpl(_InjectedOpenBox[G]):
    def __init__(self, type_arg: type[G]) -> None:
        self.type_arg = type_arg


def test_inject_wrapper_preserves_callable_metadata() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("meta")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    def _handler(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
        """Handler docstring."""
        return f"{value}:{dep.value}"

    wrapped = resolver_context.inject(_handler)
    wrapped_any = cast("Any", wrapped)

    assert wrapped.__name__ == _handler.__name__
    assert wrapped.__qualname__ == _handler.__qualname__
    assert wrapped.__doc__ == _handler.__doc__
    assert wrapped_any.__wrapped__ is _handler


def test_inject_decorator_supports_direct_form() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("direct")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject
    def handler(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
        return f"{value}:{dep.value}"

    assert getattr(handler, "__diwire_inject_wrapper__", False) is True
    injected_handler = cast("Any", handler)
    assert injected_handler("ok") == "ok:direct"


def test_inject_decorator_supports_factory_form() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("factory")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject()
    def handler(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
        return f"{value}:{dep.value}"

    injected_handler = cast("Any", handler)
    assert injected_handler("ok") == "ok:factory"


def test_inject_signature_removes_injected_parameters() -> None:
    container = Container()

    @resolver_context.inject
    def handler(
        value: str,
        dep: Injected[_InjectedSyncDependency],
        mode: str = "safe",
    ) -> tuple[str, str]:
        return value, mode

    parameters = tuple(inspect.signature(handler).parameters)
    assert parameters == ("value", "mode")


def test_inject_signature_removes_from_context_parameters() -> None:
    container = Container()

    @resolver_context.inject(scope=Scope.REQUEST)
    def handler(
        value: str,
        context_value: FromContext[int],
        mode: str = "safe",
    ) -> tuple[str, int, str]:
        return value, context_value, mode

    parameters = tuple(inspect.signature(handler).parameters)
    assert parameters == ("value", "mode")


def test_inject_allows_explicit_override_for_injected_parameter() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("container")
    custom = _InjectedSyncDependency("custom")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject
    def handler(dep: Injected[_InjectedSyncDependency]) -> str:
        return dep.value

    injected_handler = cast("Any", handler)
    assert injected_handler() == "container"
    assert injected_handler(dep=custom) == "custom"


@pytest.mark.asyncio
async def test_inject_supports_async_callables() -> None:
    container = Container()
    dependency = _InjectedAsyncDependency("async")
    container.add_instance(dependency, provides=_InjectedAsyncDependency)

    @resolver_context.inject
    async def handler(value: str, dep: Injected[_InjectedAsyncDependency]) -> str:
        return f"{value}:{dep.value}"

    injected_handler = cast("Any", handler)
    assert await injected_handler("ok") == "ok:async"


@pytest.mark.asyncio
async def test_inject_async_allows_explicit_override_for_injected_parameter() -> None:
    container = Container()
    dependency = _InjectedAsyncDependency("container")
    custom = _InjectedAsyncDependency("custom")
    container.add_instance(dependency, provides=_InjectedAsyncDependency)

    @resolver_context.inject
    async def handler(dep: Injected[_InjectedAsyncDependency]) -> str:
        return dep.value

    injected_handler = cast("Any", handler)
    assert await injected_handler() == "container"
    assert await injected_handler(dep=custom) == "custom"


def test_inject_uses_internal_resolver_when_provided() -> None:
    container = Container()
    resolved = _InjectedSyncDependency("provided")
    resolver = _ResolverStub(resolved)

    @resolver_context.inject
    def handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    result = injected_handler(diwire_resolver=resolver)

    assert result is resolved
    assert resolver.sync_calls == 1
    assert container._root_resolver is None


@pytest.mark.asyncio
async def test_inject_async_uses_internal_resolver_aresolve_when_provided() -> None:
    container = Container()
    resolved = _InjectedAsyncDependency("provided")
    resolver = _ResolverStub(resolved)

    @resolver_context.inject
    async def handler(dep: Injected[_InjectedAsyncDependency]) -> _InjectedAsyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    result = await injected_handler(diwire_resolver=resolver)

    assert result is resolved
    assert resolver.async_calls == 1
    assert resolver.sync_calls == 0
    assert container._root_resolver is None


def test_inject_falls_back_to_compiled_root_resolver() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("root")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject
    def handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    result = injected_handler()

    assert result is dependency
    assert container._root_resolver is not None


def test_inject_resolves_from_context_when_scope_is_opened_with_internal_context_kwarg() -> None:
    container = Container()

    @resolver_context.inject(scope=Scope.REQUEST)
    def handler(value: FromContext[int]) -> int:
        return value

    injected_handler = cast("Any", handler)
    assert injected_handler(diwire_context={int: 7}) == 7
    assert injected_handler(value=8) == 8


def test_inject_context_kwarg_without_scope_opening_raises_clear_error() -> None:
    container = Container()

    @resolver_context.inject(auto_open_scope=False)
    def handler(value: FromContext[int]) -> int:
        return value

    injected_handler = cast("Any", handler)
    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="was provided but no new scope was opened",
    ):
        injected_handler(diwire_context={int: 7})


def test_inject_sync_raises_for_async_dependency_chain() -> None:
    async def _provide_dependency() -> _InjectedAsyncDependency:
        return _InjectedAsyncDependency("async")

    container = Container()
    container.add_factory(_provide_dependency, provides=_InjectedAsyncDependency)

    @resolver_context.inject
    def handler(dep: Injected[_InjectedAsyncDependency]) -> _InjectedAsyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    with pytest.raises(
        DIWireAsyncDependencyInSyncContextError,
        match="requires asynchronous resolution",
    ):
        injected_handler()


def test_inject_infers_scope_depth_from_dependency_graph() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add(
        _RequestConsumer,
        provides=_RequestConsumer,
        scope=Scope.SESSION,
        lifetime=Lifetime.TRANSIENT,
    )

    @resolver_context.inject(scope=Scope.REQUEST)
    def handler(dep: Injected[_RequestConsumer]) -> _RequestConsumer:
        return dep

    with container.enter_scope(Scope.SESSION) as session_scope:
        with session_scope.enter_scope() as request_scope:
            injected_handler = cast("Any", handler)
            resolved = injected_handler(diwire_resolver=request_scope)
            assert isinstance(resolved, _RequestConsumer)
            assert isinstance(resolved.dependency, _RequestDependency)


def test_inject_auto_open_scope_from_root_without_resolver() -> None:
    container = Container()
    cleanup_called = False

    def _provide_resource() -> Generator[_RequestScopedResource, None, None]:
        nonlocal cleanup_called
        try:
            yield _RequestScopedResource()
        finally:
            cleanup_called = True

    container.add_generator(
        _provide_resource,
        provides=_RequestScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(resource: Injected[_RequestScopedResource]) -> _RequestScopedResource:
        return resource

    injected_handler = cast("Any", handler)
    resolved = injected_handler()
    assert isinstance(resolved, _RequestScopedResource)
    assert cleanup_called is True


def test_inject_auto_open_scope_from_parent_internal_resolver() -> None:
    container = Container()
    cleanup_called = False

    def _provide_resource() -> Generator[_RequestScopedResource, None, None]:
        nonlocal cleanup_called
        try:
            yield _RequestScopedResource()
        finally:
            cleanup_called = True

    container.add_generator(
        _provide_resource,
        provides=_RequestScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(resource: Injected[_RequestScopedResource]) -> _RequestScopedResource:
        return resource

    injected_handler = cast("Any", handler)
    with container.enter_scope(Scope.SESSION) as session_scope:
        resolved = injected_handler(diwire_resolver=session_scope)
        assert isinstance(resolved, _RequestScopedResource)
        assert cleanup_called is True


def test_inject_auto_open_scope_is_noop_when_target_scope_is_already_opened() -> None:
    container = Container()
    cleanup_called = False

    def _provide_resource() -> Generator[_RequestScopedResource, None, None]:
        nonlocal cleanup_called
        try:
            yield _RequestScopedResource()
        finally:
            cleanup_called = True

    container.add_generator(
        _provide_resource,
        provides=_RequestScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(resource: Injected[_RequestScopedResource]) -> _RequestScopedResource:
        return resource

    injected_handler = cast("Any", handler)
    with container.enter_scope(Scope.REQUEST) as request_scope:
        resolved = injected_handler(diwire_resolver=request_scope)
        assert isinstance(resolved, _RequestScopedResource)
        assert cleanup_called is False

    assert cleanup_called is True


def test_inject_auto_open_scope_infers_target_scope() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(auto_open_scope=True)
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    injected_handler = cast("Any", handler)
    resolved = injected_handler()
    assert isinstance(resolved, _RequestDependency)


def test_inject_auto_open_scope_infers_target_scope_after_late_registration() -> None:
    container = Container()

    @resolver_context.inject(auto_open_scope=True)
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    injected_handler = cast("Any", handler)
    resolved = injected_handler()
    assert isinstance(resolved, _RequestDependency)


def test_inject_auto_open_scope_swallow_scope_mismatch_for_deeper_resolver() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("value")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject(scope=Scope.SESSION, auto_open_scope=True)
    def handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    with container.enter_scope(Scope.REQUEST) as request_scope:
        resolved = injected_handler(diwire_resolver=request_scope)
        assert resolved is dependency


def test_inject_auto_open_scope_reuses_deeper_resolver_context_values() -> None:
    container = Container()

    @resolver_context.inject(scope=Scope.SESSION, auto_open_scope=True)
    def handler(value: FromContext[int]) -> int:
        return value

    injected_handler = cast("Any", handler)
    with container.enter_scope(Scope.SESSION, context={int: 11}) as session_scope:
        with session_scope.enter_scope(Scope.REQUEST, context={int: 22}) as request_scope:
            resolved = injected_handler(diwire_resolver=request_scope)
            assert resolved == 22


def test_inject_auto_open_scope_reraises_non_shallower_scope_mismatch() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("value")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    class _Resolver:
        def resolve(self, _dependency: object) -> _InjectedSyncDependency:
            return dependency

        def enter_scope(self, _scope: object) -> object:
            msg = "invalid transition"
            raise DIWireScopeMismatchError(msg)

    @resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    with pytest.raises(DIWireScopeMismatchError, match="invalid transition"):
        injected_handler(diwire_resolver=_Resolver())


def test_inject_auto_open_scope_raises_when_inferred_scope_has_no_matching_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)

    def _missing_scope(*, scope_level: int) -> None:
        _ = scope_level

    monkeypatch.setattr(
        container,
        "_find_scope_by_level",
        _missing_scope,
    )

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="has no matching scope in the root scope owner",
    ):

        @resolver_context.inject(auto_open_scope=True)
        def _handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
            return dep

        cast("Any", _handler)()


@pytest.mark.asyncio
async def test_inject_async_scope_mismatch_without_request_resolver() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(auto_open_scope=False)
    async def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    injected_handler = cast("Any", handler)
    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        await injected_handler()

    with container.enter_scope() as request_scope:
        resolved = await injected_handler(diwire_resolver=request_scope)
        assert isinstance(resolved, _RequestDependency)


@pytest.mark.asyncio
async def test_inject_async_auto_open_scope_without_manual_scope_management() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    async def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    injected_handler = cast("Any", handler)
    resolved = await injected_handler()
    assert isinstance(resolved, _RequestDependency)


def test_inject_nested_wrappers_propagate_same_resolver() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject
    def build_inner(dependency: Injected[_RequestDependency]) -> _NestedInnerService:
        return _NestedInnerService(dependency=dependency)

    @resolver_context.inject
    def build_outer(
        inner: Injected[_NestedInnerService],
        dependency: Injected[_RequestDependency],
    ) -> _NestedOuterService:
        return _NestedOuterService(inner=inner, dependency=dependency)

    container.add_factory(
        build_inner,
        provides=_NestedInnerService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_outer,
        provides=_NestedOuterService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_NestedOuterService)

    assert isinstance(resolved, _NestedOuterService)
    assert resolved.inner.dependency is resolved.dependency


def test_inject_rejects_explicit_scope_shallower_than_inferred() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add(
        _RequestConsumer,
        provides=_RequestConsumer,
        scope=Scope.SESSION,
        lifetime=Lifetime.TRANSIENT,
    )

    with pytest.raises(DIWireInvalidRegistrationError, match="shallower than required"):

        @resolver_context.inject(scope=Scope.SESSION)
        def _handler(dep: Injected[_RequestConsumer]) -> _RequestConsumer:
            return dep


def test_inject_revalidates_explicit_scope_after_late_registration_sync() -> None:
    container = Container(dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)

    @resolver_context.inject(scope=Scope.SESSION)
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    with pytest.raises(DIWireInvalidRegistrationError, match="shallower than required"):
        container.add(
            _RequestDependency,
            provides=_RequestDependency,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )

    assert container._providers_registrations.find_by_type(_RequestDependency) is None
    assert handler is not None


@pytest.mark.asyncio
async def test_inject_revalidates_explicit_scope_after_late_registration_async() -> None:
    container = Container(dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)

    @resolver_context.inject(scope=Scope.SESSION)
    async def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    with pytest.raises(DIWireInvalidRegistrationError, match="shallower than required"):
        container.add(
            _RequestDependency,
            provides=_RequestDependency,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )

    assert container._providers_registrations.find_by_type(_RequestDependency) is None
    assert handler is not None


def test_inject_without_explicit_scope_still_works_after_late_registration() -> None:
    container = Container()

    @resolver_context.inject
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    injected_handler = cast("Any", handler)
    with container.enter_scope() as request_scope:
        resolved = injected_handler(diwire_resolver=request_scope)

    assert isinstance(resolved, _RequestDependency)


def test_inject_revalidates_explicit_scope_on_registration_when_still_compatible() -> None:
    container = Container()

    @resolver_context.inject(scope=Scope.REQUEST)
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    injected_handler = cast("Any", handler)
    with container.enter_scope() as request_scope:
        resolved = injected_handler(diwire_resolver=request_scope)

    assert isinstance(resolved, _RequestDependency)


def test_inject_autoregister_true_registers_missing_dependency_chain() -> None:
    container = Container()

    @resolver_context.inject(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    assert container._providers_registrations.find_by_type(_AutoRoot) is not None
    assert container._providers_registrations.find_by_type(_AutoBranch) is not None
    assert container._providers_registrations.find_by_type(_AutoLeaf) is not None


def test_inject_autoregister_registers_pydantic_settings_as_singleton_factory() -> None:
    if _pydantic_settings_base is None:
        pytest.skip("pydantic_settings is unavailable")

    container = Container()

    @resolver_context.inject(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )
    def handler(settings: Injected[_InjectedSettings]) -> _InjectedSettings:
        return settings

    injected_handler = cast("Any", handler)
    first = injected_handler()
    second = injected_handler()

    settings_spec = container._providers_registrations.get_by_type(_InjectedSettings)
    assert first is second
    assert settings_spec.factory is not None
    assert settings_spec.concrete_type is None
    assert settings_spec.lifetime is Lifetime.SCOPED
    assert settings_spec.scope is Scope.APP


def test_inject_autoregister_false_disables_default_autoregistration() -> None:
    container = Container(
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE
    )

    @resolver_context.inject(dependency_registration_policy=DependencyRegistrationPolicy.IGNORE)
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    assert container._providers_registrations.find_by_type(_AutoRoot) is None


def test_inject_autoregister_none_uses_container_default_autoregistration() -> None:
    container = Container()

    @resolver_context.inject
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    assert container._providers_registrations.find_by_type(_AutoRoot) is not None


@pytest.mark.parametrize(
    "case",
    [
        _AutoregisterCase(default_enabled=True, expect_registered=True),
        _AutoregisterCase(default_enabled=False, expect_registered=False),
    ],
)
def test_inject_autoregister_none_respects_runtime_container_toggle_matrix(
    case: _AutoregisterCase,
) -> None:
    container = Container(
        dependency_registration_policy=(
            DependencyRegistrationPolicy.REGISTER_RECURSIVE
            if case.default_enabled
            else DependencyRegistrationPolicy.IGNORE
        )
    )

    @resolver_context.inject
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    is_registered = container._providers_registrations.find_by_type(_AutoRoot) is not None
    assert is_registered is case.expect_registered


def test_inject_autoregister_uses_explicit_scope_seed() -> None:
    container = Container()

    @resolver_context.inject(
        scope=Scope.REQUEST,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    root_spec = container._providers_registrations.get_by_type(_AutoRoot)
    branch_spec = container._providers_registrations.get_by_type(_AutoBranch)
    leaf_spec = container._providers_registrations.get_by_type(_AutoLeaf)
    assert root_spec.scope is Scope.REQUEST
    assert branch_spec.scope is Scope.REQUEST
    assert leaf_spec.scope is Scope.REQUEST


def test_inject_rejects_reserved_internal_resolver_parameter_name() -> None:
    container = Container()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):

        @resolver_context.inject
        def _handler(
            diwire_resolver: object,
            /,
            dep: Injected[_InjectedSyncDependency],
        ) -> None:
            _ = dep


def test_inject_rejects_reserved_internal_context_parameter_name() -> None:
    container = Container()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):

        @resolver_context.inject
        def _handler(
            diwire_context: object,
            /,
            dep: Injected[_InjectedSyncDependency],
        ) -> None:
            _ = dep


def test_internal_inject_callable_rejects_reserved_internal_resolver_parameter_name() -> None:
    container = Container()

    def _handler(
        diwire_resolver: object,
        /,
        dep: Injected[_InjectedSyncDependency],
    ) -> None:
        _ = dep

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):
        container._inject_callable(
            callable_obj=_handler,
            scope=None,
            dependency_registration_policy=None,
            auto_open_scope=True,
        )


def test_internal_inject_callable_rejects_reserved_internal_context_parameter_name() -> None:
    container = Container()

    def _handler(
        diwire_context: object,
        /,
        dep: Injected[_InjectedSyncDependency],
    ) -> None:
        _ = dep

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):
        container._inject_callable(
            callable_obj=_handler,
            scope=None,
            dependency_registration_policy=None,
            auto_open_scope=True,
        )


def test_inject_preserves_component_annotated_dependency_key() -> None:
    container = Container()

    def provide_primary() -> PrimaryDatabase:
        return _PrimaryDatabase()

    container.add_factory(provide_primary)

    @resolver_context.inject
    def handler(database: Injected[PrimaryDatabase]) -> _Database:
        return database

    injected_handler = cast("Any", handler)
    resolved = injected_handler()

    assert isinstance(resolved, _PrimaryDatabase)


def test_inject_scope_mismatch_is_raised_when_no_compatible_resolver_is_provided() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(auto_open_scope=False)
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    injected_handler = cast("Any", handler)
    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        injected_handler()


def test_inject_wrapper_does_not_forward_internal_resolver_kwarg_to_user_callable() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("value")
    resolver = _ResolverStub(dependency)

    @resolver_context.inject
    def handler(
        dep: Injected[_InjectedSyncDependency],
        **kwargs: object,
    ) -> tuple[str, bool]:
        return dep.value, "diwire_resolver" in kwargs

    injected_handler = cast("Any", handler)
    value, has_internal_kwarg = injected_handler(diwire_resolver=resolver)

    assert value == "value"
    assert has_internal_kwarg is False


def test_inject_decorated_method_keeps_descriptor_binding_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("bound")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    class _Handler:
        @resolver_context.inject
        def run(self, dep: Injected[_InjectedSyncDependency]) -> str:
            return dep.value

    handler = _Handler()
    run_method = cast("Any", handler.run)
    assert run_method() == "bound"


def test_inject_staticmethod_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("static")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    class _Handler:
        @staticmethod
        @resolver_context.inject
        def run(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
            return f"{value}:{dep.value}"

    class_callable = cast("Any", _Handler.run)
    instance_callable = cast("Any", _Handler().run)

    assert class_callable("ok") == "ok:static"
    assert instance_callable("ok") == "ok:static"


def test_inject_classmethod_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("class")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    class _Handler:
        label = "handler"

        @classmethod
        @resolver_context.inject
        def run(cls, dep: Injected[_InjectedSyncDependency]) -> str:
            return f"{cls.label}:{dep.value}"

    class_callable = cast("Any", _Handler.run)
    instance_callable = cast("Any", _Handler().run)

    assert class_callable() == "handler:class"
    assert instance_callable() == "handler:class"


def test_inject_callable_object_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("callable")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    class _Handler:
        def __call__(self, value: str, dep: Injected[_InjectedSyncDependency]) -> str:
            return f"{value}:{dep.value}"

    wrapped = resolver_context.inject(_Handler().__call__)
    wrapped_callable = cast("Any", wrapped)

    assert tuple(inspect.signature(wrapped).parameters) == ("value",)
    assert wrapped_callable("ok") == "ok:callable"


def test_inject_with_no_injected_params_is_noop_runtime() -> None:
    container = Container()

    @resolver_context.inject
    def handler(value: str) -> str:
        return value

    injected_handler = cast("Any", handler)
    assert tuple(inspect.signature(handler).parameters) == ("value",)
    assert injected_handler("ok") == "ok"
    assert getattr(handler, "__diwire_inject_wrapper__", False) is True


def test_inject_keyword_only_parameter_resolution() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("keyword-only")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject
    def handler(*, dep: Injected[_InjectedSyncDependency]) -> str:
        return dep.value

    injected_handler = cast("Any", handler)
    assert tuple(inspect.signature(handler).parameters) == ()
    assert injected_handler() == "keyword-only"


def test_inject_positional_only_parameter_resolution() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("positional-only")
    container.add_instance(dependency, provides=_InjectedSyncDependency)

    @resolver_context.inject
    def handler(value: str, dep: Injected[_InjectedSyncDependency], /) -> str:
        return f"{value}:{dep.value}"

    parameters = tuple(inspect.signature(handler).parameters.values())
    injected_handler = cast("Any", handler)

    assert len(parameters) == 1
    assert parameters[0].name == "value"
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
    assert injected_handler("ok") == "ok:positional-only"


def test_inject_reserved_kwarg_rejection_on_methods() -> None:
    container = Container()

    def _run(
        self: object,
        diwire_resolver: object,
        /,
        dep: Injected[_InjectedSyncDependency],
    ) -> None:
        _ = dep

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):

        class _Handler:
            run = resolver_context.inject(_run)


def test_resolve_injected_dependency_handles_empty_and_missing_marker_annotations() -> None:
    container = Container()

    assert container._resolve_injected_dependency(annotation=inspect.Signature.empty) is None
    assert container._resolve_injected_dependency(annotation=Annotated[int, "marker"]) is None


def test_resolve_injected_dependency_handles_invalid_annotated_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()
    monkeypatch.setattr(injection_module, "get_origin", lambda _annotation: Annotated)
    monkeypatch.setattr(injection_module, "get_args", lambda _annotation: (int,))

    assert container._resolve_injected_dependency(annotation=object()) is None


def test_pop_inject_context_handles_none_and_invalid_mapping_values() -> None:
    container = Container()
    kwargs_with_none = {injection_module.INJECT_CONTEXT_KWARG: None}

    assert container._pop_inject_context(kwargs_with_none) is None
    assert injection_module.INJECT_CONTEXT_KWARG not in kwargs_with_none

    kwargs_with_invalid = {injection_module.INJECT_CONTEXT_KWARG: "not-a-mapping"}
    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="must be a mapping or None",
    ):
        container._pop_inject_context(kwargs_with_invalid)


def test_enter_scope_if_needed_raises_for_legacy_resolver_with_context_kwarg() -> None:
    container = Container()

    class _LegacyResolver:
        def enter_scope(self, _scope: object) -> object:
            return object()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="does not support context-aware scope entry",
    ):
        container._enter_scope_if_needed(
            base_resolver=cast("Any", _LegacyResolver()),
            target_scope=Scope.REQUEST,
            context={int: 1},
        )


def test_infer_dependency_scope_level_uses_cache_and_handles_cycle_guard() -> None:
    container = Container()
    container.add(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    cache: dict[Any, int] = {}
    first = container._infer_dependency_scope_level(
        dependency=_RequestDependency,
        cache=cache,
        in_progress=set(),
    )
    second = container._infer_dependency_scope_level(
        dependency=_RequestDependency,
        cache=cache,
        in_progress=set(),
    )
    cycle_guard = container._infer_dependency_scope_level(
        dependency=_RequestDependency,
        cache={},
        in_progress={_RequestDependency},
    )

    assert first == Scope.REQUEST.level
    assert second == first
    assert cycle_guard == Scope.REQUEST.level


def test_inject_resolves_open_generic_dependency_via_wrapper_fallback() -> None:
    container = Container()
    container.add(_InjectedOpenBoxImpl, provides=_InjectedOpenBox)

    @resolver_context.inject
    def handler(box: Injected[_InjectedOpenBox[str]]) -> str:
        resolved_box = cast("Any", box)
        return resolved_box.type_arg.__name__

    injected_handler = cast("Any", handler)
    assert injected_handler() == "str"


def test_is_registered_in_resolver_fallback_checks_container_and_open_generic_registrations() -> (
    None
):
    container = Container()
    resolver_without_registered_checker = cast("Any", object())

    assert (
        container._is_registered_in_resolver(
            resolver=resolver_without_registered_checker,
            dependency=_InjectedOpenBox[str],
        )
        is False
    )

    dependency = _InjectedSyncDependency("registered")
    container.add_instance(dependency, provides=_InjectedSyncDependency)
    assert (
        container._is_registered_in_resolver(
            resolver=resolver_without_registered_checker,
            dependency=_InjectedSyncDependency,
        )
        is True
    )

    container.add(_InjectedOpenBoxImpl, provides=_InjectedOpenBox)
    assert (
        container._is_registered_in_resolver(
            resolver=resolver_without_registered_checker,
            dependency=_InjectedOpenBox[str],
        )
        is True
    )
