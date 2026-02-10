from __future__ import annotations

import inspect
from typing import Annotated, Any, NamedTuple, cast

import pytest

import diwire.injection as injection_module
from diwire.container import Container
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireInvalidRegistrationError,
    DIWireScopeMismatchError,
)
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


def test_inject_wrapper_preserves_callable_metadata() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("meta")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    def _handler(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
        """Handler docstring."""
        return f"{value}:{dep.value}"

    wrapped = container.inject(_handler)
    wrapped_any = cast("Any", wrapped)

    assert wrapped.__name__ == _handler.__name__
    assert wrapped.__qualname__ == _handler.__qualname__
    assert wrapped.__doc__ == _handler.__doc__
    assert wrapped_any.__wrapped__ is _handler


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


@pytest.mark.asyncio
async def test_inject_async_uses_internal_resolver_aresolve_when_provided() -> None:
    container = Container()
    resolved = _InjectedAsyncDependency("provided")
    resolver = _ResolverStub(resolved)

    @container.inject
    async def handler(dep: Injected[_InjectedAsyncDependency]) -> _InjectedAsyncDependency:
        return dep

    injected_handler = cast("Any", handler)
    result = await injected_handler(__diwire_resolver=resolver)

    assert result is resolved
    assert resolver.async_calls == 1
    assert resolver.sync_calls == 0
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


def test_inject_sync_raises_for_async_dependency_chain() -> None:
    async def _provide_dependency() -> _InjectedAsyncDependency:
        return _InjectedAsyncDependency("async")

    container = Container()
    container.register_factory(_InjectedAsyncDependency, factory=_provide_dependency)

    @container.inject
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


@pytest.mark.asyncio
async def test_inject_async_scope_mismatch_without_request_resolver() -> None:
    container = Container()
    container.register_concrete(
        _RequestDependency,
        concrete_type=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    async def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    injected_handler = cast("Any", handler)
    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        await injected_handler()

    with container.enter_scope() as request_scope:
        resolved = await injected_handler(__diwire_resolver=request_scope)
        assert isinstance(resolved, _RequestDependency)


def test_inject_nested_wrappers_propagate_same_resolver() -> None:
    container = Container()
    container.register_concrete(
        _RequestDependency,
        concrete_type=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    def build_inner(dependency: Injected[_RequestDependency]) -> _NestedInnerService:
        return _NestedInnerService(dependency=dependency)

    @container.inject
    def build_outer(
        inner: Injected[_NestedInnerService],
        dependency: Injected[_RequestDependency],
    ) -> _NestedOuterService:
        return _NestedOuterService(inner=inner, dependency=dependency)

    container.register_factory(
        _NestedInnerService,
        factory=build_inner,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.register_factory(
        _NestedOuterService,
        factory=build_outer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_NestedOuterService)

    assert isinstance(resolved, _NestedOuterService)
    assert resolved.inner.dependency is resolved.dependency


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
    container = Container(autoregister_dependencies=case.default_enabled)

    @container.inject
    def handler(dep: Injected[_AutoRoot]) -> _AutoRoot:
        return dep

    assert handler is not None
    is_registered = container._providers_registrations.find_by_type(_AutoRoot) is not None
    assert is_registered is case.expect_registered


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


def test_inject_wrapper_does_not_forward_internal_resolver_kwarg_to_user_callable() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("value")
    resolver = _ResolverStub(dependency)

    @container.inject
    def handler(
        dep: Injected[_InjectedSyncDependency],
        **kwargs: object,
    ) -> tuple[str, bool]:
        return dep.value, "__diwire_resolver" in kwargs

    injected_handler = cast("Any", handler)
    value, has_internal_kwarg = injected_handler(__diwire_resolver=resolver)

    assert value == "value"
    assert has_internal_kwarg is False


def test_inject_decorated_method_keeps_descriptor_binding_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("bound")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    class _Handler:
        @container.inject
        def run(self, dep: Injected[_InjectedSyncDependency]) -> str:
            return dep.value

    handler = _Handler()
    run_method = cast("Any", handler.run)
    assert run_method() == "bound"


def test_inject_staticmethod_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("static")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    class _Handler:
        @staticmethod
        @container.inject
        def run(value: str, dep: Injected[_InjectedSyncDependency]) -> str:
            return f"{value}:{dep.value}"

    class_callable = cast("Any", _Handler.run)
    instance_callable = cast("Any", _Handler().run)

    assert class_callable("ok") == "ok:static"
    assert instance_callable("ok") == "ok:static"


def test_inject_classmethod_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("class")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    class _Handler:
        label = "handler"

        @classmethod
        @container.inject
        def run(cls, dep: Injected[_InjectedSyncDependency]) -> str:
            return f"{cls.label}:{dep.value}"

    class_callable = cast("Any", _Handler.run)
    instance_callable = cast("Any", _Handler().run)

    assert class_callable() == "handler:class"
    assert instance_callable() == "handler:class"


def test_inject_callable_object_behavior() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("callable")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    class _Handler:
        def __call__(self, value: str, dep: Injected[_InjectedSyncDependency]) -> str:
            return f"{value}:{dep.value}"

    wrapped = container.inject(_Handler().__call__)
    wrapped_callable = cast("Any", wrapped)

    assert tuple(inspect.signature(wrapped).parameters) == ("value",)
    assert wrapped_callable("ok") == "ok:callable"


def test_inject_with_no_injected_params_is_noop_runtime() -> None:
    container = Container()

    @container.inject
    def handler(value: str) -> str:
        return value

    injected_handler = cast("Any", handler)
    assert tuple(inspect.signature(handler).parameters) == ("value",)
    assert injected_handler("ok") == "ok"
    assert getattr(handler, "__diwire_inject_wrapper__", False) is True


def test_inject_keyword_only_parameter_resolution() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("keyword-only")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    @container.inject
    def handler(*, dep: Injected[_InjectedSyncDependency]) -> str:
        return dep.value

    injected_handler = cast("Any", handler)
    assert tuple(inspect.signature(handler).parameters) == ()
    assert injected_handler() == "keyword-only"


def test_inject_positional_only_parameter_resolution() -> None:
    container = Container()
    dependency = _InjectedSyncDependency("positional-only")
    container.register_instance(_InjectedSyncDependency, instance=dependency)

    @container.inject
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
        __diwire_resolver: object,
        /,
        dep: Injected[_InjectedSyncDependency],
    ) -> None:
        _ = dep

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):

        class _Handler:
            run = container.inject(_run)


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
