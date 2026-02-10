from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypeVar, cast, overload

from diwire.container import Container
from diwire.exceptions import DIWireContainerNotSetError, DIWireInvalidRegistrationError
from diwire.injection import (
    INJECT_RESOLVER_KWARG,
    INJECT_WRAPPER_MARKER,
    InjectedCallableInspector,
)
from diwire.lock_mode import LockMode
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

_RegistrationMethod: TypeAlias = Literal[
    "register_instance",
    "register_concrete",
    "register_factory",
    "register_generator",
    "register_context_manager",
]


@dataclass(frozen=True, slots=True)
class _RegistrationOperation:
    """Container registration operation replayed by ContainerContext."""

    method_name: _RegistrationMethod
    kwargs: dict[str, Any]

    def apply(self, container: Container) -> None:
        registration_kwargs = {
            key: list(value) if key == "dependencies" and value is not None else value
            for key, value in self.kwargs.items()
        }
        registration_method = cast("Callable[..., Any]", getattr(container, self.method_name))
        registration_method(**registration_kwargs)


class ContainerContext:
    """Deferred-registration container context with one shared active container.

    The active container binding is process-global for this ``ContainerContext`` instance.
    It is not task-local or thread-local.
    """

    def __init__(self) -> None:
        self._container: Container | None = None
        self._operations: list[_RegistrationOperation] = []
        self._injected_callable_inspector = InjectedCallableInspector()

    def set_current(self, container: Container) -> None:
        """Set the shared active container and replay deferred registrations.

        This method is expected to be called once during container creation/bootstrap.
        """
        self._container = container
        self._populate(container)

    def get_current(self) -> Container:
        """Return the shared active container or raise when not bound."""
        if self._container is None:
            msg = (
                "Container is not set for container_context. "
                "Call container_context.set_current(container) before using container_context."
            )
            raise DIWireContainerNotSetError(msg)
        return self._container

    def _populate(self, container: Container) -> None:
        for operation in self._operations:
            operation.apply(container)

    def _record_operation(self, operation: _RegistrationOperation) -> None:
        self._operations.append(operation)
        if self._container is not None:
            operation.apply(self._container)

    def _record_registration(
        self,
        *,
        method_name: _RegistrationMethod,
        registration_kwargs: dict[str, Any],
    ) -> None:
        normalized_kwargs = registration_kwargs.copy()
        dependencies = normalized_kwargs.get("dependencies")
        if dependencies is not None:
            normalized_kwargs["dependencies"] = tuple(dependencies)

        self._record_operation(
            _RegistrationOperation(
                method_name=method_name,
                kwargs=normalized_kwargs,
            ),
        )

    def register_instance(
        self,
        provides: type[T] | None = None,
        *,
        instance: T,
    ) -> None:
        """Register an instance provider for replay and immediate binding when available."""
        self._record_registration(
            method_name="register_instance",
            registration_kwargs={
                "provides": provides,
                "instance": instance,
            },
        )

    def register_concrete(  # noqa: PLR0913
        self,
        provides: type[T] | None = None,
        *,
        concrete_type: type[T] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[type[T]], type[T]]:
        """Register a concrete provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_concrete: type[T]) -> type[T]:
            self.register_concrete(
                provides=provides,
                concrete_type=decorated_concrete,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_concrete

        if provides is None and concrete_type is None:
            return decorator

        normalized_provides = provides if provides is not None else concrete_type
        normalized_concrete = concrete_type if concrete_type is not None else provides

        self._record_registration(
            method_name="register_concrete",
            registration_kwargs={
                "provides": normalized_provides,
                "concrete_type": normalized_concrete,
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
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
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[F], F]:
        """Register a factory provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_factory: F) -> F:
            self.register_factory(
                provides=provides,
                factory=cast("Callable[..., T] | Callable[..., Awaitable[T]]", decorated_factory),
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_factory

        if factory is None:
            return decorator

        self._record_registration(
            method_name="register_factory",
            registration_kwargs={
                "provides": provides,
                "factory": cast("FactoryProvider[Any]", factory),
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
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
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[F], F]:
        """Register a generator provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

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
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_generator

        if generator is None:
            return decorator

        self._record_registration(
            method_name="register_generator",
            registration_kwargs={
                "provides": provides,
                "generator": cast("GeneratorProvider[Any]", generator),
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
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
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | None = None,
    ) -> Callable[[F], F]:
        """Register a context manager provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_context_manager: F) -> F:
            self.register_context_manager(
                provides=provides,
                context_manager=cast(
                    "Callable[..., AbstractContextManager[T]] | Callable[..., AbstractAsyncContextManager[T]]",
                    decorated_context_manager,
                ),
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_context_manager

        if context_manager is None:
            return decorator

        self._record_registration(
            method_name="register_context_manager",
            registration_kwargs={
                "provides": provides,
                "context_manager": cast("ContextManagerProvider[Any]", context_manager),
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
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

    def _resolve_container_injected_callable(
        self,
        *,
        callable_obj: InjectableF,
        scope: BaseScope | None,
        autoregister_dependencies: bool | None,
    ) -> Callable[..., Any]:
        container = self.get_current()
        injected_decorator = container.inject(
            scope=scope,
            autoregister_dependencies=autoregister_dependencies,
        )
        return injected_decorator(callable_obj)

    def _inject_callable(
        self,
        *,
        callable_obj: InjectableF,
        scope: BaseScope | None,
        autoregister_dependencies: bool | None,
    ) -> InjectableF:
        signature = inspect.signature(callable_obj)
        if INJECT_RESOLVER_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved parameter "
                f"'{INJECT_RESOLVER_KWARG}'."
            )
            raise DIWireInvalidRegistrationError(msg)

        inspected_callable = self._injected_callable_inspector.inspect_callable(callable_obj)

        if inspect.iscoroutinefunction(callable_obj):

            @functools.wraps(callable_obj)
            async def _async_injected(*args: Any, **kwargs: Any) -> Any:
                injected = self._resolve_container_injected_callable(
                    callable_obj=callable_obj,
                    scope=scope,
                    autoregister_dependencies=autoregister_dependencies,
                )
                async_injected = cast("Callable[..., Awaitable[Any]]", injected)
                return await async_injected(*args, **kwargs)

            wrapped_callable: Callable[..., Any] = _async_injected
        else:

            @functools.wraps(callable_obj)
            def _sync_injected(*args: Any, **kwargs: Any) -> Any:
                injected = self._resolve_container_injected_callable(
                    callable_obj=callable_obj,
                    scope=scope,
                    autoregister_dependencies=autoregister_dependencies,
                )
                return injected(*args, **kwargs)

            wrapped_callable = _sync_injected

        wrapped_callable.__signature__ = inspected_callable.public_signature  # type: ignore[attr-defined]
        wrapped_callable.__dict__[INJECT_WRAPPER_MARKER] = True
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
