from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypeVar, cast, overload

from diwire.container import Container
from diwire.exceptions import DIWireContainerNotSetError, DIWireInvalidRegistrationError
from diwire.injection import (
    INJECT_CONTEXT_KWARG,
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
C = TypeVar("C", bound=type[Any])

_RegistrationMethod: TypeAlias = Literal[
    "add_instance",
    "add_concrete",
    "add_factory",
    "add_generator",
    "add_context_manager",
]


@dataclass(frozen=True, slots=True)
class _RegistrationOperation:
    """Container registration operation replayed by ContainerContext."""

    method_name: _RegistrationMethod
    kwargs: dict[str, Any]

    def apply(self, container: Container) -> None:
        registration_kwargs = {
            key: list(value) if key == "dependencies" and isinstance(value, tuple) else value
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
        if isinstance(dependencies, list):
            normalized_kwargs["dependencies"] = tuple(dependencies)

        self._record_operation(
            _RegistrationOperation(
                method_name=method_name,
                kwargs=normalized_kwargs,
            ),
        )

    def add_instance(
        self,
        instance: T,
        *,
        provides: Any | Literal["infer"] = "infer",
    ) -> None:
        """Register an instance provider for replay and immediate binding when available."""
        provides_value = cast("Any", provides)
        if provides_value == "infer":
            resolved_provides: Any = type(instance)
        elif provides_value is not None:
            resolved_provides = provides_value
        else:
            msg = "add_instance() parameter 'provides' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        self._record_registration(
            method_name="add_instance",
            registration_kwargs={
                "provides": resolved_provides,
                "instance": instance,
            },
        )

    @overload
    def add_concrete(
        self,
        concrete_type: type[Any],
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_concrete(
        self,
        concrete_type: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[C], C]: ...

    def add_concrete(  # noqa: PLR0913
        self,
        concrete_type: type[Any] | Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | Callable[[C], C]:
        """Register a concrete provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_concrete: C) -> C:
            self.add_concrete(
                decorated_concrete,
                provides=provides,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_concrete

        if concrete_type == "from_decorator":
            return decorator

        normalized_provides, normalized_concrete = self._normalize_concrete_registration_types(
            provides=provides,
            concrete_type=concrete_type,
        )
        self._validate_registration_provides(
            method_name="add_concrete",
            provides=normalized_provides,
        )
        self._validate_registration_scope(
            method_name="add_concrete",
            scope=scope,
        )
        self._validate_registration_lifetime(
            method_name="add_concrete",
            lifetime=lifetime,
        )
        self._validate_registration_dependencies(
            method_name="add_concrete",
            dependencies=dependencies,
        )
        self._validate_registration_autoregister_dependencies(
            method_name="add_concrete",
            autoregister_dependencies=autoregister_dependencies,
        )

        self._record_registration(
            method_name="add_concrete",
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
        return None

    @overload
    def add_factory(
        self,
        factory: Callable[..., Any] | Callable[..., Awaitable[Any]],
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_factory(
        self,
        factory: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F]: ...

    def add_factory(  # noqa: PLR0913
        self,
        factory: (
            Callable[..., Any] | Callable[..., Awaitable[Any]] | Literal["from_decorator"]
        ) = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | Callable[[F], F]:
        """Register a factory provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_factory: F) -> F:
            self.add_factory(
                decorated_factory,
                provides=provides,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_factory

        factory_value = cast("Any", factory)
        if factory_value == "from_decorator":
            return decorator

        if not callable(factory_value):
            msg = "add_factory() parameter 'factory' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)

        self._validate_registration_provides(method_name="add_factory", provides=provides)
        self._validate_registration_scope(method_name="add_factory", scope=scope)
        self._validate_registration_lifetime(method_name="add_factory", lifetime=lifetime)
        self._validate_registration_dependencies(
            method_name="add_factory",
            dependencies=dependencies,
        )
        self._validate_registration_autoregister_dependencies(
            method_name="add_factory",
            autoregister_dependencies=autoregister_dependencies,
        )

        self._record_registration(
            method_name="add_factory",
            registration_kwargs={
                "provides": provides,
                "factory": cast("FactoryProvider[Any]", factory_value),
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
        )
        return None

    @overload
    def add_generator(
        self,
        generator: (
            Callable[..., Generator[Any, None, None]] | Callable[..., AsyncGenerator[Any, None]]
        ),
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_generator(
        self,
        generator: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F]: ...

    def add_generator(  # noqa: PLR0913
        self,
        generator: (
            Callable[..., Generator[Any, None, None]]
            | Callable[..., AsyncGenerator[Any, None]]
            | Literal["from_decorator"]
        ) = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | Callable[[F], F]:
        """Register a generator provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_generator: F) -> F:
            self.add_generator(
                decorated_generator,
                provides=provides,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_generator

        generator_value = cast("Any", generator)
        if generator_value == "from_decorator":
            return decorator

        if not callable(generator_value):
            msg = "add_generator() parameter 'generator' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)

        self._validate_registration_provides(method_name="add_generator", provides=provides)
        self._validate_registration_scope(method_name="add_generator", scope=scope)
        self._validate_registration_lifetime(method_name="add_generator", lifetime=lifetime)
        self._validate_registration_dependencies(
            method_name="add_generator",
            dependencies=dependencies,
        )
        self._validate_registration_autoregister_dependencies(
            method_name="add_generator",
            autoregister_dependencies=autoregister_dependencies,
        )

        self._record_registration(
            method_name="add_generator",
            registration_kwargs={
                "provides": provides,
                "generator": cast("GeneratorProvider[Any]", generator_value),
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
        )
        return None

    @overload
    def add_context_manager(
        self,
        context_manager: (
            Callable[..., AbstractContextManager[Any]]
            | Callable[..., AbstractAsyncContextManager[Any]]
        ),
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_context_manager(
        self,
        context_manager: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F]: ...

    def add_context_manager(  # noqa: PLR0913
        self,
        context_manager: (
            Callable[..., AbstractContextManager[Any]]
            | Callable[..., AbstractAsyncContextManager[Any]]
            | Literal["from_decorator"]
        ) = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | Callable[[F], F]:
        """Register a context manager provider with direct and decorator forms.

        ``lock_mode="from_container"`` is persisted and replayed unchanged.
        """

        def decorator(decorated_context_manager: F) -> F:
            self.add_context_manager(
                decorated_context_manager,
                provides=provides,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_context_manager

        context_manager_value = cast("Any", context_manager)
        if context_manager_value == "from_decorator":
            return decorator

        if not callable(context_manager_value):
            msg = (
                "add_context_manager() parameter 'context_manager' must be callable or "
                "'from_decorator'."
            )
            raise DIWireInvalidRegistrationError(msg)

        self._validate_registration_provides(
            method_name="add_context_manager",
            provides=provides,
        )
        self._validate_registration_scope(method_name="add_context_manager", scope=scope)
        self._validate_registration_lifetime(
            method_name="add_context_manager",
            lifetime=lifetime,
        )
        self._validate_registration_dependencies(
            method_name="add_context_manager",
            dependencies=dependencies,
        )
        self._validate_registration_autoregister_dependencies(
            method_name="add_context_manager",
            autoregister_dependencies=autoregister_dependencies,
        )

        self._record_registration(
            method_name="add_context_manager",
            registration_kwargs={
                "provides": provides,
                "context_manager": cast("ContextManagerProvider[Any]", context_manager_value),
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
        )
        return None

    def _normalize_concrete_registration_types(
        self,
        *,
        provides: Any | Literal["infer"],
        concrete_type: Any,
    ) -> tuple[Any, type[Any]]:
        provides_value = cast("Any", provides)
        concrete_type_value = concrete_type

        if provides_value == "infer":
            normalized_provides = concrete_type_value
        elif provides_value is not None:
            normalized_provides = provides_value
        else:
            msg = "add_concrete() parameter 'provides' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        if concrete_type_value is None:
            msg = "add_concrete() parameter 'concrete_type' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        return normalized_provides, concrete_type_value

    def _validate_registration_provides(
        self,
        *,
        method_name: str,
        provides: Any | Literal["infer"],
    ) -> None:
        provides_value = cast("Any", provides)
        if provides_value is None:
            msg = f"{method_name}() parameter 'provides' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

    def _validate_registration_scope(
        self,
        *,
        method_name: str,
        scope: BaseScope | Literal["from_container"],
    ) -> None:
        scope_value = cast("Any", scope)
        if scope_value != "from_container" and not isinstance(scope_value, BaseScope):
            msg = f"{method_name}() parameter 'scope' must be BaseScope or 'from_container'."
            raise DIWireInvalidRegistrationError(msg)

    def _validate_registration_lifetime(
        self,
        *,
        method_name: str,
        lifetime: Lifetime | Literal["from_container"],
    ) -> None:
        lifetime_value = cast("Any", lifetime)
        if lifetime_value != "from_container" and not isinstance(lifetime_value, Lifetime):
            msg = f"{method_name}() parameter 'lifetime' must be Lifetime or 'from_container'."
            raise DIWireInvalidRegistrationError(msg)

    def _validate_registration_dependencies(
        self,
        *,
        method_name: str,
        dependencies: list[ProviderDependency] | Literal["infer"],
    ) -> None:
        dependencies_value = cast("Any", dependencies)
        if dependencies_value != "infer" and not isinstance(dependencies_value, list):
            msg = f"{method_name}() parameter 'dependencies' must be a list or 'infer'."
            raise DIWireInvalidRegistrationError(msg)

    def _validate_registration_autoregister_dependencies(
        self,
        *,
        method_name: str,
        autoregister_dependencies: bool | Literal["from_container"],
    ) -> None:
        autoregister_dependencies_value = cast("Any", autoregister_dependencies)
        if autoregister_dependencies_value != "from_container" and not isinstance(
            autoregister_dependencies_value,
            bool,
        ):
            msg = (
                f"{method_name}() parameter 'autoregister_dependencies' must be bool or "
                "'from_container'."
            )
            raise DIWireInvalidRegistrationError(msg)

    @overload
    def inject(self, func: InjectableF) -> InjectableF: ...

    @overload
    def inject(
        self,
        func: Literal["from_decorator"] = "from_decorator",
        *,
        scope: BaseScope | Literal["infer"] = "infer",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
        auto_open_scope: bool = True,
    ) -> Callable[[InjectableF], InjectableF]: ...

    def inject(
        self,
        func: InjectableF | Literal["from_decorator"] = "from_decorator",
        *,
        scope: BaseScope | Literal["infer"] = "infer",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
        auto_open_scope: bool = True,
    ) -> InjectableF | Callable[[InjectableF], InjectableF]:
        """Decorate a callable with lazy injection delegated to the current container."""
        scope_value = cast("Any", scope)
        if scope_value != "infer" and not isinstance(scope_value, BaseScope):
            msg = "inject() parameter 'scope' must be BaseScope or 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        autoregister_dependencies_value = cast("Any", autoregister_dependencies)
        if autoregister_dependencies_value != "from_container" and not isinstance(
            autoregister_dependencies_value,
            bool,
        ):
            msg = "inject() parameter 'autoregister_dependencies' must be bool or 'from_container'."
            raise DIWireInvalidRegistrationError(msg)

        def decorator(callable_obj: InjectableF) -> InjectableF:
            return self._inject_callable(
                callable_obj=callable_obj,
                scope=scope_value,
                autoregister_dependencies=autoregister_dependencies_value,
                auto_open_scope=auto_open_scope,
            )

        func_value = cast("Any", func)
        if func_value == "from_decorator":
            return decorator
        if not callable(func_value):
            msg = "inject() parameter 'func' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)
        return decorator(func_value)

    def _resolve_container_injected_callable(
        self,
        *,
        callable_obj: InjectableF,
        scope: BaseScope | Literal["infer"],
        autoregister_dependencies: bool | Literal["from_container"],
        auto_open_scope: bool,
    ) -> Callable[..., Any]:
        container = self.get_current()
        injected_decorator = container.inject(
            scope=scope,
            autoregister_dependencies=autoregister_dependencies,
            auto_open_scope=auto_open_scope,
        )
        return injected_decorator(callable_obj)

    def _inject_callable(
        self,
        *,
        callable_obj: InjectableF,
        scope: BaseScope | Literal["infer"],
        autoregister_dependencies: bool | Literal["from_container"],
        auto_open_scope: bool,
    ) -> InjectableF:
        signature = inspect.signature(callable_obj)
        if INJECT_RESOLVER_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved parameter "
                f"'{INJECT_RESOLVER_KWARG}'."
            )
            raise DIWireInvalidRegistrationError(msg)
        if INJECT_CONTEXT_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved parameter "
                f"'{INJECT_CONTEXT_KWARG}'."
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
                    auto_open_scope=auto_open_scope,
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
                    auto_open_scope=auto_open_scope,
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

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
        """Enter a scope on the current bound container."""
        return self.get_current().enter_scope(scope, context=context)

    def _callable_name(self, callable_obj: Callable[..., Any]) -> str:
        return getattr(callable_obj, "__qualname__", repr(callable_obj))


container_context = ContainerContext()
