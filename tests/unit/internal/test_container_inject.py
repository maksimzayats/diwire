from __future__ import annotations

import inspect
from typing import Annotated, Any, cast

import pytest

import diwire.container as container_module
from diwire.container import Container
from diwire.exceptions import DIWireInvalidRegistrationError, DIWireScopeMismatchError
from diwire.markers import Component, Injected
from diwire.providers import Lifetime
from diwire.scope import Scope


class _InjectedSyncDependency:
    def __init__(self, value: str) -> None:
        self.value = value


class _InjectedAsyncDependency:
    def __init__(self, value: str) -> None:
        self.value = value


class _RequestDependency:
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


def test_inject_decorator_supports_direct_form() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("direct")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    @container.inject
    def handler(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
        return f"{value}:{dep.value}"

    assert getattr(handler, "__diwire_inject_wrapper__", False) is True
    injected_handler = cast("Any", handler)
    assert injected_handler("ok") == "ok:direct"


def test_inject_decorator_supports_factory_form() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("factory")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    @container.inject()
    def handler(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
        return f"{value}:{dep.value}"

    injected_handler = cast("Any", handler)
    assert injected_handler("ok") == "ok:factory"


def test_inject_signature_removes_injected_parameters() -> None:
    container = Container()

    @container.inject
    def handler(
        value: str,
        dep: Injected[_InjectedSyncDependency],
        mode: str = "safe",
    ) -> tuple[str, str]:
        return value, mode

    parameters = tuple(inspect.signature(handler).parameters)
    assert parameters == ("value", "mode")


def test_inject_allows_explicit_override_for_injected_parameter() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("container")
    custom = _InjectedSyncDependency("custom")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    @container.inject
    def handler(dep: Injected[_InjectedSyncDependency]) -> str:
        return dep.value

    injected_handler = cast("Any", handler)
    assert injected_handler() == "container"
    assert injected_handler(dep=custom) == "custom"


@pytest.mark.asyncio
async def test_inject_supports_async_callables() -> None:
    container = Container()
    dependency = _InjectedAsyncDependency("async")
    container.register_instance(_InjectedAsyncDependency, instance=dependency)

    @container.inject
    async def handler(value: str, dep: Injected[_InjectedAsyncDependency]) -> str:
        return f"{value}:{dep.value}"

    injected_handler = cast("Any", handler)
    assert await injected_handler("ok") == "ok:async"


@pytest.mark.asyncio
async def test_inject_async_allows_explicit_override_for_injected_parameter() -> None:
    container = Container()
    dependency = _InjectedAsyncDependency("container")
    custom = _InjectedAsyncDependency("custom")
    container.register_instance(_InjectedAsyncDependency, instance=dependency)

    @container.inject
    async def handler(dep: Injected[_InjectedAsyncDependency]) -> str:
        return dep.value

    injected_handler = cast("Any", handler)
    assert await injected_handler() == "container"
    assert await injected_handler(dep=custom) == "custom"


def test_inject_uses_internal_resolver_when_provided() -> None:
    container = Container()
    resolved = _InjectedSyncDependency("provided")
    resolver = _ResolverStub(resolved)

    @container.inject
    def handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    result = injected_handler(__diwire_resolver=resolver)

    assert result is resolved
    assert resolver.sync_calls == 1
    assert container._root_resolver is None


def test_inject_falls_back_to_compiled_root_resolver() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("root")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    @container.inject
    def handler(dep: Injected[_InjectedSyncDependency]) -> _InjectedSyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    result = injected_handler()

    assert result is dependency
    assert container._root_resolver is not None


def test_inject_infers_scope_depth_from_dependency_graph() -> None:
    container = Container()
    container.register_concrete(
        _RequestDependency,
        concrete_type=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _RequestConsumer,
        concrete_type=_RequestConsumer,
        scope=Scope.SESSION,
        lifetime=Lifetime.TRANSIENT,
    )

    @container.inject(scope=Scope.REQUEST)
    def handler(dep: Injected[_RequestConsumer]) -> _RequestConsumer:
        return dep

    with container.enter_scope(Scope.SESSION) as session_scope:
        with session_scope.enter_scope() as request_scope:
            injected_handler = cast("Any", handler)
            resolved = injected_handler(__diwire_resolver=request_scope)
            assert isinstance(resolved, _RequestConsumer)
            assert isinstance(resolved.dependency, _RequestDependency)


def test_inject_rejects_explicit_scope_shallower_than_inferred() -> None:
    container = Container()
    container.register_concrete(
        _RequestDependency,
        concrete_type=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_concrete(
        _RequestConsumer,
        concrete_type=_RequestConsumer,
        scope=Scope.SESSION,
        lifetime=Lifetime.TRANSIENT,
    )

    with pytest.raises(DIWireInvalidRegistrationError, match="shallower than required"):

        @container.inject(scope=Scope.SESSION)
        def _handler(dep: Injected[_RequestConsumer]) -> _RequestConsumer:
            return dep


def test_inject_autoregister_true_registers_missing_dependency_chain() -> None:
    container = Container()

    @container.inject(autoregister_dependencies=True)
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    assert container._providers_registrations.find_by_type(_AutoRoot) is not None
    assert container._providers_registrations.find_by_type(_AutoBranch) is not None
    assert container._providers_registrations.find_by_type(_AutoLeaf) is not None


def test_inject_autoregister_false_disables_default_autoregistration() -> None:
    container = Container(autoregister_dependencies=True)

    @container.inject(autoregister_dependencies=False)
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    assert container._providers_registrations.find_by_type(_AutoRoot) is None


def test_inject_autoregister_none_uses_container_default() -> None:
    container = Container(autoregister_dependencies=True)

    @container.inject
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    assert container._providers_registrations.find_by_type(_AutoRoot) is not None


def test_inject_autoregister_uses_explicit_scope_seed() -> None:
    container = Container()

    @container.inject(scope=Scope.REQUEST, autoregister_dependencies=True)
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

        @container.inject
        def _handler(
            __diwire_resolver: object,
            /,
            dep: Injected[_InjectedSyncDependency],
        ) -> None:
            _ = dep


def test_inject_preserves_component_annotated_dependency_key() -> None:
    container = Container()

    def provide_primary() -> PrimaryDatabase:
        return _PrimaryDatabase()

    container.register_factory(factory=provide_primary)

    @container.inject
    def handler(database: Injected[PrimaryDatabase]) -> _Database:
        return database

    injected_handler = cast("Any", handler)
    resolved = injected_handler()

    assert isinstance(resolved, _PrimaryDatabase)


def test_inject_scope_mismatch_is_raised_when_no_compatible_resolver_is_provided() -> None:
    container = Container()
    container.register_concrete(
        _RequestDependency,
        concrete_type=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    injected_handler = cast("Any", handler)
    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        injected_handler()


def test_resolve_injected_dependency_handles_empty_and_missing_marker_annotations() -> None:
    container = Container()

    assert container._resolve_injected_dependency(annotation=inspect.Signature.empty) is None
    assert container._resolve_injected_dependency(annotation=Annotated[int, "marker"]) is None


def test_resolve_injected_dependency_handles_invalid_annotated_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container()
    monkeypatch.setattr(container_module, "get_origin", lambda _annotation: Annotated)
    monkeypatch.setattr(container_module, "get_args", lambda _annotation: (int,))

    assert container._resolve_injected_dependency(annotation=object()) is None


def test_infer_dependency_scope_level_uses_cache_and_handles_cycle_guard() -> None:
    container = Container()
    container.register_concrete(
        _RequestDependency,
        concrete_type=_RequestDependency,
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
