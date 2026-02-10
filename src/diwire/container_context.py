from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast, overload

from diwire.container import Container
from diwire.exceptions import DIWireContainerNotSetError, DIWireInvalidRegistrationError
from diwire.injection import InjectedCallableInspector
from diwire.providers import (
    ContextManagerProvider,
    FactoryProvider,
    GeneratorProvider,
    Lifetime,
    ProviderDependency,
)
from diwire.resolvers.protocol import ResolverProtocol
from diwire.scope import BaseScope

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])
InjectableF = TypeVar("InjectableF", bound=Callable[..., Any])

_INJECT_RESOLVER_KWARG = "__diwire_resolver"
_INJECT_WRAPPER_MARKER = "__diwire_inject_wrapper__"
_CONTAINER_NOT_SET_MESSAGE = (
    "Container is not set for container_context. "
    "Call container_context.set_current(container) before using container_context."
)


class _RegistrationOperation(Protocol):
    """Container registration operation replayed by ContainerContext."""

    def apply(self, container: Container) -> None:
        """Apply the operation to a target container."""


@dataclass(frozen=True, slots=True)
class _RegisterInstanceOperation:
    provides: type[Any] | None
    instance: Any
    concurrency_safe: bool | None

    def apply(self, container: Container) -> None:
        container.register_instance(
            provides=self.provides,
            instance=self.instance,
            concurrency_safe=self.concurrency_safe,
        )


@dataclass(frozen=True, slots=True)
class _RegisterConcreteOperation:
    provides: type[Any]
    concrete_type: type[Any]
    scope: BaseScope | None
    lifetime: Lifetime | None
    dependencies: tuple[ProviderDependency, ...] | None
    concurrency_safe: bool | None
    autoregister_dependencies: bool | None

    def apply(self, container: Container) -> None:
        container.register_concrete(
            provides=self.provides,
            concrete_type=self.concrete_type,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=list(self.dependencies) if self.dependencies is not None else None,
            concurrency_safe=self.concurrency_safe,
            autoregister_dependencies=self.autoregister_dependencies,
        )


@dataclass(frozen=True, slots=True)
class _RegisterFactoryOperation:
    provides: type[Any] | None
    factory: FactoryProvider[Any]
    scope: BaseScope | None
    lifetime: Lifetime | None
    dependencies: tuple[ProviderDependency, ...] | None
    concurrency_safe: bool | None
    autoregister_dependencies: bool | None

    def apply(self, container: Container) -> None:
        container.register_factory(
            provides=self.provides,
            factory=self.factory,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=list(self.dependencies) if self.dependencies is not None else None,
            concurrency_safe=self.concurrency_safe,
            autoregister_dependencies=self.autoregister_dependencies,
        )


@dataclass(frozen=True, slots=True)
class _RegisterGeneratorOperation:
    provides: type[Any] | None
    generator: GeneratorProvider[Any]
    scope: BaseScope | None
    lifetime: Lifetime | None
    dependencies: tuple[ProviderDependency, ...] | None
    concurrency_safe: bool | None
    autoregister_dependencies: bool | None

    def apply(self, container: Container) -> None:
        container.register_generator(
            provides=self.provides,
            generator=self.generator,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=list(self.dependencies) if self.dependencies is not None else None,
            concurrency_safe=self.concurrency_safe,
            autoregister_dependencies=self.autoregister_dependencies,
        )


@dataclass(frozen=True, slots=True)
class _RegisterContextManagerOperation:
    provides: type[Any] | None
    context_manager: ContextManagerProvider[Any]
    scope: BaseScope | None
    lifetime: Lifetime | None
    dependencies: tuple[ProviderDependency, ...] | None
    concurrency_safe: bool | None
    autoregister_dependencies: bool | None

    def apply(self, container: Container) -> None:
        container.register_context_manager(
            provides=self.provides,
            context_manager=self.context_manager,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=list(self.dependencies) if self.dependencies is not None else None,
            concurrency_safe=self.concurrency_safe,
            autoregister_dependencies=self.autoregister_dependencies,
        )


class ContainerContext:
    """Deferred-registration container context with a single active container binding."""

    def __init__(self) -> None:
        self._container: Container | None = None
        self._operations: list[_RegistrationOperation] = []
        self._injected_callable_inspector = InjectedCallableInspector()

    def set_current(self, container: Container) -> None:
        """Set the active container and replay all deferred registrations into it."""
        self._container = container
        self._populate(container)

    def get_current(self) -> Container:
        """Return the active container or raise when no container has been bound."""
        if self._container is None:
            raise DIWireContainerNotSetError(_CONTAINER_NOT_SET_MESSAGE)
        return self._container

    def _populate(self, container: Container) -> None:
        for operation in self._operations:
            operation.apply(container)

    def _record_operation(self, operation: _RegistrationOperation) -> None:
        self._operations.append(operation)
        if self._container is not None:
            operation.apply(self._container)

    def register_instance(
        self,
        provides: type[T] | None = None,
        *,
        instance: T,
        concurrency_safe: bool | None = None,
    ) -> None:
        """Register an instance provider for replay and immediate binding when available."""
        self._record_operation(
            _RegisterInstanceOperation(
                provides=cast("type[Any] | None", provides),
                instance=instance,
                concurrency_safe=concurrency_safe,
            ),
        )

    def register_concrete(  # noqa: PLR0913
        self,
        provides: type[T] | None = None,
        *,
        concrete_type: type[T] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        concurrency_safe: bool | None = None,
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[type[T]], type[T]]:
        """Register a concrete provider with direct and decorator forms."""

        def decorator(decorated_concrete: type[T]) -> type[T]:
            self.register_concrete(
                provides=provides,
                concrete_type=decorated_concrete,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_concrete

        if provides is None and concrete_type is None:
            return decorator

        normalized_provides = provides if provides is not None else concrete_type
        normalized_concrete = concrete_type if concrete_type is not None else provides

        self._record_operation(
            _RegisterConcreteOperation(
                provides=cast("type[Any]", normalized_provides),
                concrete_type=cast("type[Any]", normalized_concrete),
                scope=scope,
                lifetime=lifetime,
                dependencies=tuple(dependencies) if dependencies is not None else None,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            ),
        )
        return decorator

    def register_factory(  # noqa: PLR0913
        self,
        provides: type[T] | None = None,
        *,
        factory: Callable[..., T] | Callable[..., Awaitable[T]] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        concurrency_safe: bool | None = None,
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[F], F]:
        """Register a factory provider with direct and decorator forms."""

        def decorator(decorated_factory: F) -> F:
            self.register_factory(
                provides=provides,
                factory=cast("Callable[..., T] | Callable[..., Awaitable[T]]", decorated_factory),
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_factory

        if factory is None:
            return decorator

        self._record_operation(
            _RegisterFactoryOperation(
                provides=cast("type[Any] | None", provides),
                factory=cast("FactoryProvider[Any]", factory),
                scope=scope,
                lifetime=lifetime,
                dependencies=tuple(dependencies) if dependencies is not None else None,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            ),
        )
        return decorator

    def register_generator(  # noqa: PLR0913
        self,
        provides: type[T] | None = None,
        *,
        generator: (
            Callable[..., Generator[T, None, None]] | Callable[..., AsyncGenerator[T, None]] | None
        ),
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        concurrency_safe: bool | None = None,
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[F], F]:
        """Register a generator provider with direct and decorator forms."""

        def decorator(decorated_generator: F) -> F:
            self.register_generator(
                provides=provides,
                generator=cast(
                    "Callable[..., Generator[T, None, None]] | Callable[..., AsyncGenerator[T, None]]",
                    decorated_generator,
                ),
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_generator

        if generator is None:
            return decorator

        self._record_operation(
            _RegisterGeneratorOperation(
                provides=cast("type[Any] | None", provides),
                generator=cast("GeneratorProvider[Any]", generator),
                scope=scope,
                lifetime=lifetime,
                dependencies=tuple(dependencies) if dependencies is not None else None,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            ),
        )
        return decorator

    def register_context_manager(  # noqa: PLR0913
        self,
        provides: type[T] | None = None,
        *,
        context_manager: (
            Callable[..., AbstractContextManager[T]]
            | Callable[..., AbstractAsyncContextManager[T]]
            | None
        ) = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        concurrency_safe: bool | None = None,
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[F], F]:
        """Register a context manager provider with direct and decorator forms."""

        def decorator(decorated_context_manager: F) -> F:
            self.register_context_manager(
                provides=provides,
                context_manager=cast(
                    "Callable[..., AbstractContextManager[T]]"
                    " | Callable[..., AbstractAsyncContextManager[T]]",
                    decorated_context_manager,
                ),
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_context_manager

        if context_manager is None:
            return decorator

        self._record_operation(
            _RegisterContextManagerOperation(
                provides=cast("type[Any] | None", provides),
                context_manager=cast("ContextManagerProvider[Any]", context_manager),
                scope=scope,
                lifetime=lifetime,
                dependencies=tuple(dependencies) if dependencies is not None else None,
                concurrency_safe=concurrency_safe,
                autoregister_dependencies=autoregister_dependencies,
            ),
        )
        return decorator

    @overload
    def inject(self, func: InjectableF) -> InjectableF: ...

    @overload
    def inject(
        self,
        func: None = None,
        *,
        scope: BaseScope | None = None,
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[InjectableF], InjectableF]: ...

    def inject(
        self,
        func: InjectableF | None = None,
        *,
        scope: BaseScope | None = None,
        autoregister_dependencies: bool | None = None,
    ) -> InjectableF | Callable[[InjectableF], InjectableF]:
        """Decorate a callable with lazy injection delegated to the current container."""

        def decorator(callable_obj: InjectableF) -> InjectableF:
            return self._inject_callable(
                callable_obj=callable_obj,
                scope=scope,
                autoregister_dependencies=autoregister_dependencies,
            )

        if func is None:
            return decorator
        return decorator(func)

    def _inject_callable(
        self,
        *,
        callable_obj: InjectableF,
        scope: BaseScope | None,
        autoregister_dependencies: bool | None,
    ) -> InjectableF:
        signature = inspect.signature(callable_obj)
        if _INJECT_RESOLVER_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved parameter "
                f"'{_INJECT_RESOLVER_KWARG}'."
            )
            raise DIWireInvalidRegistrationError(msg)

        inspected_callable = self._injected_callable_inspector.inspect_callable(callable_obj)

        if inspect.iscoroutinefunction(callable_obj):

            @functools.wraps(callable_obj)
            async def _async_injected(*args: Any, **kwargs: Any) -> Any:
                container = self.get_current()
                injected_decorator = container.inject(
                    scope=scope,
                    autoregister_dependencies=autoregister_dependencies,
                )
                injected = injected_decorator(callable_obj)
                async_injected = cast("Callable[..., Awaitable[Any]]", injected)
                return await async_injected(*args, **kwargs)

            wrapped_callable: Callable[..., Any] = _async_injected
        else:

            @functools.wraps(callable_obj)
            def _sync_injected(*args: Any, **kwargs: Any) -> Any:
                container = self.get_current()
                injected_decorator = container.inject(
                    scope=scope,
                    autoregister_dependencies=autoregister_dependencies,
                )
                injected = injected_decorator(callable_obj)
                sync_injected = cast("Callable[..., Any]", injected)
                return sync_injected(*args, **kwargs)

            wrapped_callable = _sync_injected

        wrapped_callable.__signature__ = inspected_callable.public_signature  # type: ignore[attr-defined]
        wrapped_callable.__dict__[_INJECT_WRAPPER_MARKER] = True
        return cast("InjectableF", wrapped_callable)

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        """Resolve dependency via the current bound container."""
        return self.get_current().resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        """Resolve dependency asynchronously via the current bound container."""
        return await self.get_current().aresolve(dependency)

    def enter_scope(self, scope: BaseScope | None = None) -> ResolverProtocol:
        """Enter a scope on the current bound container."""
        return self.get_current().enter_scope(scope)

    def _callable_name(self, callable_obj: Callable[..., Any]) -> str:
        return getattr(callable_obj, "__qualname__", repr(callable_obj))


container_context = ContainerContext()
