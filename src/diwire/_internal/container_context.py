from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypeVar, cast, overload

from diwire._internal.container import Container
from diwire._internal.injection import (
    INJECT_CONTEXT_KWARG,
    INJECT_RESOLVER_KWARG,
    INJECT_WRAPPER_MARKER,
    InjectedCallableInspector,
)
from diwire._internal.lock_mode import LockMode
from diwire._internal.markers import Component
from diwire._internal.providers import (
    ContextManagerProvider,
    FactoryProvider,
    GeneratorProvider,
    Lifetime,
)
from diwire._internal.resolvers.protocol import ResolverProtocol
from diwire._internal.scope import BaseScope
from diwire.exceptions import DIWireContainerNotSetError, DIWireInvalidRegistrationError

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
    "decorate",
]


@dataclass(frozen=True, slots=True)
class _RegistrationOperation:
    """Container registration operation replayed by ContainerContext."""

    method_name: _RegistrationMethod
    kwargs: dict[str, Any]

    def apply(self, container: Container) -> None:
        registration_method = cast("Callable[..., Any]", getattr(container, self.method_name))
        registration_method(**self.kwargs)


class ContainerContext:
    """Proxy registrations and resolution through a process-global container.

    ``ContainerContext`` supports a deferred-registration workflow: registrations
    called before binding are recorded and replayed when ``set_current`` binds an
    actual container. Resolution APIs still require a bound container.

    The binding is process-global for this instance (not task-local/thread-local),
    which is convenient for application startup but important for tests that run
    in parallel.
    """

    def __init__(self) -> None:
        self._container: Container | None = None
        self._operations: list[_RegistrationOperation] = []
        self._injected_callable_inspector = InjectedCallableInspector()

    def set_current(self, container: Container) -> None:
        """Bind the active container and replay all deferred registrations.

        Args:
            container: Container to bind as the active target.

        Notes:
            Existing recorded operations are replayed immediately in original
            order. Future registration calls are recorded and also applied
            eagerly to the bound container.

        """
        self._container = container
        self._populate(container)

    def get_current(self) -> Container:
        """Return the bound container.

        Returns:
            The currently bound container.

        Raises:
            DIWireContainerNotSetError: If no container has been bound yet.

        """
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
        if isinstance(dependencies, Mapping):
            normalized_kwargs["dependencies"] = dict(dependencies)

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
        component: Component | Any | None = None,
    ) -> None:
        """Record and apply an instance registration on the current container.

        Args:
            instance: Instance value to register.
            provides: Dependency key to bind. ``"infer"`` uses ``type(instance)``.
            component: Optional component marker value forwarded to the container.

        Raises:
            DIWireInvalidRegistrationError: If ``provides`` is ``None``.

        Notes:
            If unbound, this registration is queued and replayed by
            ``set_current``. If bound, it is also applied immediately.

        """
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
                "component": component,
            },
        )

    @overload
    def add_concrete(
        self,
        concrete_type: type[Any],
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_concrete(
        self,
        concrete_type: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[C], C]: ...

    def add_concrete(  # noqa: PLR0913
        self,
        concrete_type: type[Any] | Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[C], C] | None:
        """Record and apply a concrete registration with direct/decorator forms.

        Args:
            concrete_type: Concrete class to register, or ``"from_decorator"``.
            provides: Dependency key produced by the provider.
            component: Optional component marker value forwarded to the container.
            scope: Provider scope or ``"from_container"``.
            lifetime: Provider lifetime or ``"from_container"``.
            dependencies: Explicit dependency mapping or ``"infer"``.
            lock_mode: Lock strategy or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration.

        Returns:
            ``None`` in direct mode or decorator callable in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If registration arguments are invalid.

        Notes:
            ``lock_mode="from_container"`` is stored verbatim and resolved by the
            bound container during replay/application.

        """

        def decorator(decorated_concrete: C) -> C:
            self.add_concrete(
                decorated_concrete,
                provides=provides,
                component=component,
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
                "component": component,
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
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_factory(
        self,
        factory: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
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
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F] | None:
        """Record and apply a factory registration with direct/decorator forms.

        Args:
            factory: Factory callable to register, or ``"from_decorator"``.
            provides: Dependency key produced by the provider.
            component: Optional component marker value forwarded to the container.
            scope: Provider scope or ``"from_container"``.
            lifetime: Provider lifetime or ``"from_container"``.
            dependencies: Explicit dependency mapping or ``"infer"``.
            lock_mode: Lock strategy or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration.

        Returns:
            ``None`` in direct mode or decorator callable in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If registration arguments are invalid.

        """

        def decorator(decorated_factory: F) -> F:
            self.add_factory(
                decorated_factory,
                provides=provides,
                component=component,
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
                "component": component,
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
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_generator(
        self,
        generator: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
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
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F] | None:
        """Record and apply a generator registration with direct/decorator forms.

        Args:
            generator: Generator provider, or ``"from_decorator"``.
            provides: Dependency key produced by the provider.
            component: Optional component marker value forwarded to the container.
            scope: Provider scope or ``"from_container"``.
            lifetime: Provider lifetime or ``"from_container"``.
            dependencies: Explicit dependency mapping or ``"infer"``.
            lock_mode: Lock strategy or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration.

        Returns:
            ``None`` in direct mode or decorator callable in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If registration arguments are invalid.

        """

        def decorator(decorated_generator: F) -> F:
            self.add_generator(
                decorated_generator,
                provides=provides,
                component=component,
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
                "component": component,
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
        context_manager: ContextManagerProvider[Any],
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None: ...

    @overload
    def add_context_manager(
        self,
        context_manager: Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F]: ...

    def add_context_manager(  # noqa: PLR0913
        self,
        context_manager: ContextManagerProvider[Any] | Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: Component | Any | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> Callable[[F], F] | None:
        """Record and apply a context-manager registration.

        Args:
            context_manager: Context-manager provider, or ``"from_decorator"``.
            provides: Dependency key produced by the provider.
            component: Optional component marker value forwarded to the container.
            scope: Provider scope or ``"from_container"``.
            lifetime: Provider lifetime or ``"from_container"``.
            dependencies: Explicit dependency mapping or ``"infer"``.
            lock_mode: Lock strategy or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration.

        Returns:
            ``None`` in direct mode or decorator callable in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If registration arguments are invalid.

        """

        def decorator(decorated_context_manager: F) -> F:
            self.add_context_manager(
                decorated_context_manager,
                provides=provides,
                component=component,
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
                "component": component,
                "scope": scope,
                "lifetime": lifetime,
                "dependencies": dependencies,
                "lock_mode": lock_mode,
                "autoregister_dependencies": autoregister_dependencies,
            },
        )
        return None

    def decorate(
        self,
        *,
        provides: Any,
        component: Component | Any | None = None,
        decorator: Callable[..., Any],
        inner_parameter: str | None = None,
    ) -> None:
        """Record and apply a provider decoration operation.

        Args:
            provides: Dependency key to decorate.
            component: Optional component marker value forwarded to the container.
            decorator: Factory-style callable wrapping the inner dependency.
            inner_parameter: Optional decorator parameter name receiving inner.

        Raises:
            DIWireInvalidRegistrationError: If arguments are invalid.

        """
        if provides is None:
            msg = "decorate() parameter 'provides' must not be None."
            raise DIWireInvalidRegistrationError(msg)
        decorator_value = cast("Any", decorator)
        if not callable(decorator_value):
            msg = "decorate() parameter 'decorator' must be callable."
            raise DIWireInvalidRegistrationError(msg)
        unwrapped = inspect.unwrap(decorator_value)
        if inspect.isgeneratorfunction(unwrapped) or inspect.isasyncgenfunction(unwrapped):
            msg = (
                "decorate() parameter 'decorator' must be a sync/async factory-style "
                "callable, not a generator or async-generator function."
            )
            raise DIWireInvalidRegistrationError(msg)

        self._record_registration(
            method_name="decorate",
            registration_kwargs={
                "provides": provides,
                "component": component,
                "decorator": cast("Callable[..., Any]", decorator_value),
                "inner_parameter": inner_parameter,
            },
        )

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
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"],
    ) -> None:
        dependencies_value = cast("Any", dependencies)
        if dependencies_value == "infer":
            return
        if not isinstance(dependencies_value, Mapping):
            msg = (
                f"{method_name}() parameter 'dependencies' must be a "
                "mapping[Any, inspect.Parameter] or 'infer'."
            )
            raise DIWireInvalidRegistrationError(msg)
        if not all(
            isinstance(parameter, inspect.Parameter) for parameter in dependencies_value.values()
        ):
            msg = (
                f"{method_name}() parameter 'dependencies' must be a "
                "mapping[Any, inspect.Parameter] or 'infer'."
            )
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
        """Decorate a callable and delegate injection to the bound container.

        Args:
            func: Callable to wrap, or ``"from_decorator"``.
            scope: Scope passed through to ``Container.inject``.
            autoregister_dependencies: Setting passed through to
                ``Container.inject``.
            auto_open_scope: Scope behavior passed through to ``Container.inject``.

        Returns:
            Wrapped callable, or a decorator when ``func="from_decorator"``.

        Raises:
            DIWireInvalidRegistrationError: If wrapper arguments are invalid.
            DIWireContainerNotSetError: At call time when no container is bound.

        Notes:
            The wrapper resolves the current container lazily on each invocation.

        """
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
        """Resolve a dependency via the currently bound container.

        Args:
            dependency: Dependency key to resolve.

        Returns:
            Resolved dependency value.

        Raises:
            DIWireContainerNotSetError: If no container is currently bound.
            DIWireDependencyNotRegisteredError: If the dependency is not
                registered in strict mode.
            DIWireScopeMismatchError: If a deeper scope is required.
            DIWireAsyncDependencyInSyncContextError: If the selected chain is
                async-only.
            DIWireInvalidGenericTypeArgumentError: If generic arguments violate
                TypeVar constraints.

        """
        return self.get_current().resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        """Resolve a dependency asynchronously via the bound container.

        Args:
            dependency: Dependency key to resolve.

        Returns:
            Resolved dependency value.

        Raises:
            DIWireContainerNotSetError: If no container is currently bound.
            DIWireDependencyNotRegisteredError: If the dependency is not
                registered in strict mode.
            DIWireScopeMismatchError: If a deeper scope is required.
            DIWireInvalidGenericTypeArgumentError: If generic arguments violate
                TypeVar constraints.

        """
        return await self.get_current().aresolve(dependency)

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
        """Enter scope on the currently bound container.

        Args:
            scope: Target scope, or ``None`` for default next transition.
            context: Optional context mapping for ``FromContext[...]`` lookups.

        Returns:
            Scoped resolver produced by the bound container.

        Raises:
            DIWireContainerNotSetError: If no container is currently bound.
            DIWireScopeMismatchError: If the requested transition is invalid.

        """
        return self.get_current().enter_scope(scope, context=context)

    def _callable_name(self, callable_obj: Callable[..., Any]) -> str:
        return getattr(callable_obj, "__qualname__", repr(callable_obj))


container_context = ContainerContext()
"""Process-global container proxy used by module-level registration decorators.

Bind once during application startup, then use decorators from
``diwire.registration_decorators`` safely across modules.

Examples:
    .. code-block:: python

        container = Container()
        container_context.set_current(container)
"""
