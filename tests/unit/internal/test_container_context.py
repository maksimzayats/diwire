from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from typing import Any, Generic, TypeVar, cast

import pytest

import diwire
from diwire.container import Container
from diwire.container_context import ContainerContext
from diwire.exceptions import (
    DIWireContainerNotSetError,
    DIWireInvalidRegistrationError,
    DIWireScopeMismatchError,
)
from diwire.lock_mode import LockMode
from diwire.markers import FromContext, Injected
from diwire.providers import Lifetime, ProviderDependency
from diwire.scope import Scope


class _Service:
    def __init__(self, value: str = "service") -> None:
        self.value = value


class _DecoratedService:
    def __init__(self, inner: _Service) -> None:
        self.inner = inner


class _RequestDependency:
    pass


class _AsyncService:
    def __init__(self, value: str) -> None:
        self.value = value


T = TypeVar("T")


class _OpenBox(Generic[T]):
    pass


class _OpenBoxA(_OpenBox[T]):
    def __init__(self, type_arg: type[T]) -> None:
        self.type_arg = type_arg


class _OpenBoxB(_OpenBox[T]):
    def __init__(self, type_arg: type[T]) -> None:
        self.type_arg = type_arg


def test_top_level_container_context_export_is_available() -> None:
    assert isinstance(diwire.container_context, ContainerContext)


def test_get_current_raises_when_context_is_unbound() -> None:
    context = ContainerContext()

    with pytest.raises(DIWireContainerNotSetError, match="set_current"):
        context.get_current()


def test_resolve_raises_when_context_is_unbound() -> None:
    context = ContainerContext()

    with pytest.raises(DIWireContainerNotSetError, match="set_current"):
        context.resolve(_Service)


@pytest.mark.asyncio
async def test_aresolve_raises_when_context_is_unbound() -> None:
    context = ContainerContext()

    with pytest.raises(DIWireContainerNotSetError, match="set_current"):
        await context.aresolve(_Service)


def test_enter_scope_raises_when_context_is_unbound() -> None:
    context = ContainerContext()

    with pytest.raises(DIWireContainerNotSetError, match="set_current"):
        context.enter_scope()


def test_inject_wrapper_runtime_call_raises_when_unbound() -> None:
    context = ContainerContext()

    @context.inject
    def handler(service: Injected[_Service]) -> _Service:
        return service

    with pytest.raises(DIWireContainerNotSetError, match="set_current"):
        cast("Any", handler)()


@pytest.mark.asyncio
async def test_inject_async_wrapper_runtime_call_raises_when_unbound() -> None:
    context = ContainerContext()

    @context.inject
    async def handler(service: Injected[_AsyncService]) -> _AsyncService:
        return service

    with pytest.raises(DIWireContainerNotSetError, match="set_current"):
        await cast("Any", handler)()


def test_register_before_bind_replays_on_set_current() -> None:
    context = ContainerContext()

    class _ConcreteService:
        pass

    context.add_concrete(_ConcreteService)

    container = Container()
    context.set_current(container)

    resolved = container.resolve(_ConcreteService)
    assert isinstance(resolved, _ConcreteService)


def test_decorate_before_bind_replays_on_set_current() -> None:
    context = ContainerContext()
    context.decorate(provides=_Service, decorator=_DecoratedService)
    context.add_factory(lambda: _Service("base"), provides=_Service)

    container = Container()
    context.set_current(container)

    resolved = container.resolve(_Service)
    assert isinstance(resolved, _DecoratedService)
    assert resolved.inner.value == "base"


def test_replay_preserves_canonical_open_key_override_order() -> None:
    context = ContainerContext()
    context.add_concrete(_OpenBoxA, provides=_OpenBox)
    context.add_concrete(_OpenBoxB, provides=_OpenBox[T])

    container = Container()
    context.set_current(container)

    resolved = container.resolve(_OpenBox[int])
    assert isinstance(resolved, _OpenBoxB)


def test_register_factory_persists_and_replays_from_container_lock_mode_sentinel() -> None:
    context = ContainerContext()

    def build_service() -> _Service:
        return _Service("factory")

    context.add_factory(build_service, provides=_Service)
    operation = context._operations[0]
    assert operation.kwargs["lock_mode"] == "from_container"

    container = Container(lock_mode=LockMode.NONE)
    context.set_current(container)

    spec = container._providers_registrations.get_by_type(_Service)
    assert spec.lock_mode is LockMode.NONE


def test_register_concrete_supports_decorator_form() -> None:
    context = ContainerContext()

    class _DecoratedService:
        pass

    register_decorator = cast("Any", context.add_concrete())
    register_decorator(_DecoratedService)

    container = Container()
    context.set_current(container)

    assert isinstance(container.resolve(_DecoratedService), _DecoratedService)


def test_register_context_manager_supports_decorator_form() -> None:
    context = ContainerContext()

    @contextmanager
    def provide_request_dependency() -> Generator[_RequestDependency, None, None]:
        yield _RequestDependency()

    register_decorator = cast("Any", context.add_context_manager())
    returned_context_manager = register_decorator(provide_request_dependency)

    container = Container()
    context.set_current(container)

    assert returned_context_manager is provide_request_dependency
    assert isinstance(container.resolve(_RequestDependency), _RequestDependency)


def test_set_current_replays_operations_for_each_bound_container() -> None:
    context = ContainerContext()
    context.add_instance(_Service("registered"))

    first = Container()
    context.set_current(first)

    second = Container()
    context.set_current(second)

    assert first.resolve(_Service).value == "registered"
    assert second.resolve(_Service).value == "registered"


def test_register_while_bound_applies_to_current_container_immediately() -> None:
    context = ContainerContext()
    container = Container()
    context.set_current(container)

    context.add_instance(_Service("bound"))

    assert container.resolve(_Service).value == "bound"


def test_private_populate_is_not_exposed_publicly() -> None:
    context = ContainerContext()

    assert hasattr(context, "_populate")
    assert not hasattr(context, "populate")


def test_inject_signature_matches_container_signature_filtering() -> None:
    context = ContainerContext()
    container = Container()

    def handler(
        value: str,
        service: Injected[_Service],
        /,
        *,
        mode: str = "safe",
        request: Injected[_RequestDependency],
    ) -> tuple[str, str]:
        return value, mode

    container_wrapped = container.inject(handler)
    context_wrapped = context.inject(handler)

    assert inspect.signature(container_wrapped) == inspect.signature(context_wrapped)


def test_inject_wrapper_preserves_metadata_and_marker() -> None:
    context = ContainerContext()

    def handler(value: str, service: Injected[_Service]) -> str:
        """Context handler docstring."""
        return f"{value}:{service.value}"

    wrapped = context.inject(handler)
    wrapped_any = cast("Any", wrapped)

    assert wrapped.__name__ == handler.__name__
    assert wrapped.__qualname__ == handler.__qualname__
    assert wrapped.__doc__ == handler.__doc__
    assert wrapped_any.__wrapped__ is handler
    assert getattr(wrapped, "__diwire_inject_wrapper__", False) is True


def test_inject_supports_factory_form() -> None:
    context = ContainerContext()
    context.add_instance(_Service("factory"))
    context.set_current(Container())

    @context.inject()
    def handler(service: Injected[_Service]) -> str:
        return service.value

    assert cast("Any", handler)() == "factory"


def test_inject_supports_auto_open_scope_forwarding() -> None:
    context = ContainerContext()
    context.add_concrete(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    context.set_current(Container())

    @context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(dep: Injected[_RequestDependency]) -> _RequestDependency:
        return dep

    resolved = cast("Any", handler)()
    assert isinstance(resolved, _RequestDependency)


def test_inject_rejects_reserved_internal_resolver_parameter_name() -> None:
    context = ContainerContext()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):

        @context.inject
        def _handler(__diwire_resolver: object, /, service: Injected[_Service]) -> None:
            _ = service


def test_inject_rejects_reserved_internal_context_parameter_name() -> None:
    context = ContainerContext()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="cannot declare reserved parameter",
    ):

        @context.inject
        def _handler(__diwire_context: object, /, service: Injected[_Service]) -> None:
            _ = service


def test_inject_method_descriptor_behavior() -> None:
    context = ContainerContext()
    context.add_instance(_Service("bound"))
    context.set_current(Container())

    class _Handler:
        @context.inject
        def run(self, service: Injected[_Service]) -> str:
            return service.value

    handler = _Handler()
    bound_method = cast("Any", handler.run)
    assert bound_method() == "bound"


def test_inject_staticmethod_and_classmethod_descriptor_behavior() -> None:
    context = ContainerContext()
    context.add_instance(_Service("value"))
    context.set_current(Container())

    class _Handler:
        label = "handler"

        @staticmethod
        @context.inject
        def run_static(value: str, service: Injected[_Service]) -> str:
            return f"{value}:{service.value}"

        @classmethod
        @context.inject
        def run_class(cls, service: Injected[_Service]) -> str:
            return f"{cls.label}:{service.value}"

    run_static_class = cast("Any", _Handler.run_static)
    run_static_instance = cast("Any", _Handler().run_static)
    run_class_class = cast("Any", _Handler.run_class)
    run_class_instance = cast("Any", _Handler().run_class)

    assert run_static_class("ok") == "ok:value"
    assert run_static_instance("ok") == "ok:value"
    assert run_class_class() == "handler:value"
    assert run_class_instance() == "handler:value"


@pytest.mark.asyncio
async def test_aresolve_delegates_to_current_container() -> None:
    context = ContainerContext()

    async def provide_async_service() -> _AsyncService:
        return _AsyncService("async")

    context.add_factory(provide_async_service, provides=_AsyncService)
    context.set_current(Container())

    resolved = await context.aresolve(_AsyncService)
    assert isinstance(resolved, _AsyncService)
    assert resolved.value == "async"


def test_enter_scope_delegates_to_current_container() -> None:
    context = ContainerContext()
    context.add_concrete(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    context.set_current(Container())

    with context.enter_scope() as request_scope:
        resolved = request_scope.resolve(_RequestDependency)

    assert isinstance(resolved, _RequestDependency)


def test_enter_scope_delegates_context_to_current_container() -> None:
    context = ContainerContext()
    context.set_current(Container())

    with context.enter_scope(Scope.REQUEST, context={int: 42}) as request_scope:
        assert request_scope.resolve(FromContext[int]) == 42


def test_resolve_delegation_preserves_scope_rules() -> None:
    context = ContainerContext()
    context.add_concrete(
        _RequestDependency,
        provides=_RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    context.set_current(Container())

    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        context.resolve(_RequestDependency)


@pytest.mark.asyncio
async def test_context_inject_async_wrapper_works_after_binding() -> None:
    context = ContainerContext()
    context.add_instance(_AsyncService("ready"))

    @context.inject
    async def handler(service: Injected[_AsyncService]) -> str:
        return service.value

    context.set_current(Container())

    assert await cast("Any", handler)() == "ready"


def test_register_generator_and_context_manager_replay() -> None:
    context = ContainerContext()

    def provide_generator() -> Generator[_Service, None, None]:
        yield _Service("generator")

    @contextmanager
    def provide_context_manager() -> Generator[_RequestDependency, None, None]:
        yield _RequestDependency()

    context.add_generator(provide_generator, provides=_Service)
    context.add_context_manager(provide_context_manager, provides=_RequestDependency)

    container = Container()
    context.set_current(container)

    assert container.resolve(_Service).value == "generator"
    assert isinstance(container.resolve(_RequestDependency), _RequestDependency)


def test_registration_dependencies_are_copied_for_replay() -> None:
    context = ContainerContext()
    context.add_instance(_Service("dep"))

    def provide_request(service: _Service) -> _RequestDependency:
        _ = service
        return _RequestDependency()

    explicit_dependencies = [
        ProviderDependency(
            provides=_Service,
            parameter=inspect.Parameter(
                "service",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
        ),
    ]
    context.add_factory(
        provide_request,
        provides=_RequestDependency,
        dependencies=explicit_dependencies,
    )
    explicit_dependencies.clear()

    container = Container()
    context.set_current(container)

    assert isinstance(container.resolve(_RequestDependency), _RequestDependency)


@pytest.mark.asyncio
async def test_register_async_generator_replay() -> None:
    context = ContainerContext()

    async def provide_async_generator() -> AsyncGenerator[_AsyncService, None]:
        yield _AsyncService("async-generator")

    context.add_generator(provide_async_generator, provides=_AsyncService)
    context.set_current(Container())

    resolved = await context.aresolve(_AsyncService)
    assert isinstance(resolved, _AsyncService)
    assert resolved.value == "async-generator"
