from __future__ import annotations

import asyncio
import contextlib
import inspect
import itertools
import threading
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
from contextlib import AsyncExitStack, ExitStack
from types import FunctionType, MethodType
from typing import (
    Any,
    ClassVar,
    TypeVar,
    cast,
    get_origin,
    overload,
)

from diwire.compiled_providers import (
    ArgsTypeProvider,
    CompiledProvider,
    FactoryProvider,
    InstanceProvider,
    ScopedSingletonArgsProvider,
    ScopedSingletonProvider,
    SingletonArgsTypeProvider,
    SingletonFactoryProvider,
    SingletonTypeProvider,
    TypeProvider,
)
from diwire.container_helpers import (
    _get_generic_origin_and_args,
    _get_return_annotation,
    _is_any_type,
    _is_async_factory,
    _is_method_descriptor,
    _is_typevar,
    _is_union_type,
    _OpenGenericRegistration,
    _ResolvedDependencies,
    _type_arg_matches_constraint,
    _unwrap_method_descriptor,
)
from diwire.container_injection import (
    _AsyncInjectedFunction,
    _AsyncScopedInjectedFunction,
    _InjectedFunction,
    _ScopedInjectedFunction,
)
from diwire.container_locks import LockManager
from diwire.container_resolution_stack import _get_resolution_stack
from diwire.container_scopes import ScopedContainer, _current_scope, _ScopeId
from diwire.defaults import (
    DEFAULT_AUTOREGISTER_IGNORES,
    DEFAULT_AUTOREGISTER_LIFETIME,
    DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES,
)
from diwire.dependencies import DependenciesExtractor, ParameterInfo
from diwire.exceptions import (
    DIWireAsyncCleanupWithoutEventLoopError,
    DIWireAsyncDependencyInSyncContextError,
    DIWireAsyncGeneratorFactoryDidNotYieldError,
    DIWireAsyncGeneratorFactoryWithoutScopeError,
    DIWireCircularDependencyError,
    DIWireComponentSpecifiedError,
    DIWireConcreteClassRequiresClassError,
    DIWireContainerClosedError,
    DIWireDecoratorFactoryMissingReturnAnnotationError,
    DIWireError,
    DIWireGeneratorFactoryDidNotYieldError,
    DIWireGeneratorFactoryUnsupportedLifetimeError,
    DIWireGeneratorFactoryWithoutScopeError,
    DIWireIgnoredServiceError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireMissingDependenciesError,
    DIWireNotAClassError,
    DIWireOpenGenericRegistrationError,
    DIWireOpenGenericResolutionError,
    DIWireScopedWithoutScopeError,
    DIWireScopeMismatchError,
    DIWireServiceNotRegisteredError,
    DIWireUnionTypeError,
)
from diwire.registry import Registration
from diwire.service_key import Component, ServiceKey
from diwire.types import Factory, Lifetime

T = TypeVar("T", bound=Any)
_C = TypeVar("_C", bound=type)  # For class decorator


class Container:
    """Dependency injection container for registering and resolving services.

    Supports automatic registration, lifetime singleton/transient, and factory patterns.
    """

    # Class-level counter for generating unique scope IDs (faster than UUID)
    _scope_counter: ClassVar[itertools.count[int]] = itertools.count()

    __slots__ = (
        "_active_scopes",
        "_active_scopes_lock",
        "_async_deps_cache",
        "_async_scope_exit_stacks",
        "_auto_compile",
        "_autoregister",
        "_autoregister_default_lifetime",
        "_autoregister_ignores",
        "_autoregister_registration_factories",
        "_cleanup_tasks",
        "_closed",
        "_compiled_providers",
        "_dependencies_extractor",
        "_has_scoped_registrations",
        "_is_compiled",
        "_locks",
        "_open_generic_registry",
        "_registry",
        "_scope_exit_stacks",
        "_scoped_compiled_providers",
        "_scoped_instances",
        "_scoped_open_generic_registry",
        "_scoped_registry",
        "_singletons",
        "_type_providers",
        "_type_singletons",
    )

    def __init__(
        self,
        *,
        autoregister: bool = True,
        autoregister_ignores: set[type[Any]] | None = None,
        autoregister_registration_factories: dict[type[Any], Callable[[Any], Registration]]
        | None = None,
        autoregister_default_lifetime: Lifetime = DEFAULT_AUTOREGISTER_LIFETIME,
        auto_compile: bool = True,
    ) -> None:
        self._autoregister = autoregister
        self._autoregister_ignores = autoregister_ignores or DEFAULT_AUTOREGISTER_IGNORES
        self._autoregister_registration_factories = (
            autoregister_registration_factories or DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES
        )
        self._autoregister_default_lifetime = autoregister_default_lifetime
        self._auto_compile = auto_compile

        self._singletons: dict[ServiceKey, Any] = {}
        # Flat scoped instance cache: (scope_cache_key, service_key) -> instance
        self._scoped_instances: dict[
            tuple[tuple[tuple[str | None, int], ...], ServiceKey],
            Any,
        ] = {}
        self._registry: dict[ServiceKey, Registration] = {}
        self._scoped_registry: dict[tuple[ServiceKey, str], Registration] = {}
        self._open_generic_registry: dict[
            tuple[type, Component | None],
            _OpenGenericRegistration,
        ] = {}
        self._scoped_open_generic_registry: dict[
            tuple[type, Component | None, str],
            _OpenGenericRegistration,
        ] = {}
        # Scope exit stacks keyed by tuple for consistency
        self._scope_exit_stacks: dict[tuple[tuple[str | None, int], ...], ExitStack] = {}
        self._async_scope_exit_stacks: dict[tuple[tuple[str | None, int], ...], AsyncExitStack] = {}
        # Background cleanup tasks (to prevent garbage collection)
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

        self._dependencies_extractor = DependenciesExtractor()

        # Compiled providers for optimized resolution
        self._compiled_providers: dict[ServiceKey, CompiledProvider] = {}
        # Compiled scoped providers: (service_key, scope_name) -> provider
        self._scoped_compiled_providers: dict[tuple[ServiceKey, str], CompiledProvider] = {}
        self._is_compiled: bool = False

        # Fast type-based lookup caches (bypasses ServiceKey creation for simple types)
        self._type_singletons: dict[type, Any] = {}
        self._type_providers: dict[type, CompiledProvider] = {}

        # Track if any scoped registrations exist to skip ContextVar lookups
        self._has_scoped_registrations: bool = False

        # Cache for async dependency info (Phase 4 optimization)
        self._async_deps_cache: dict[ServiceKey, frozenset[ServiceKey]] = {}

        # Lock manager for singleton and scoped singleton resolution
        self._locks = LockManager()

        # Track active scopes for imperative close()
        self._active_scopes: list[ScopedContainer] = []
        self._active_scopes_lock = threading.Lock()
        self._closed = False

        self.register(type(self), instance=self, lifetime=Lifetime.SINGLETON)

    # Overload 1: Bare class decorator - @container.register
    # Must come first to match the direct decorator pattern
    @overload
    def register(self, key: _C, /) -> _C: ...

    # Overload 2: Bare factory function decorator - @container.register
    @overload
    def register(self, key: Callable[..., T], /) -> Callable[..., T]: ...

    # Overload 3: Parameterized decorator without key - @container.register(lifetime=...)
    # Returns a decorator that accepts classes or functions
    @overload
    def register(
        self,
        key: None = None,
        /,
        factory: None = None,
        instance: None = None,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,
        concrete_class: type | None = ...,
    ) -> Callable[[T], T]: ...

    # Overload 4: Interface decorator - @container.register(Interface, lifetime=...)
    # When a type is passed with optional keyword args (no factory/instance/concrete_class),
    # returns a decorator
    @overload
    def register(
        self,
        key: type,
        /,
        *,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,
    ) -> Callable[[T], T]: ...

    # Overload 5: String key decorator - @container.register("key", lifetime=...)
    # When a string is passed as key with optional keyword args (no factory/instance/concrete_class),
    # returns a decorator
    @overload
    def register(
        self,
        key: str,
        /,
        *,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,
    ) -> Callable[[T], T]: ...

    # Overload 6: Direct call with explicit key - container.register(Interface, concrete_class=...)
    @overload
    def register(
        self,
        key: Any,
        /,
        factory: Factory | None = ...,
        instance: Any | None = ...,
        lifetime: Lifetime = ...,
        scope: str | None = ...,
        is_async: bool | None = ...,
        concrete_class: type | None = ...,
    ) -> None: ...

    def register(
        self,
        key: Any | None = None,
        /,
        factory: Factory | None = None,
        instance: Any | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        scope: str | None = None,
        is_async: bool | None = None,
        concrete_class: type | None = None,
    ) -> Any:
        """Register a service with the container.

        Can be used as:
        - Bare class decorator: @container.register
        - Parameterized decorator: @container.register(lifetime=Lifetime.SINGLETON)
        - Interface decorator: @container.register(IService) on a class
        - Factory function decorator: @container.register (with return annotation)
        - Direct call: container.register(IService, concrete_class=MyService)

        Args:
            key: The service key (interface/type) to register under. When None, returns
                a decorator. When used with @container.register(Interface) on a class,
                the decorated class becomes the implementation.
            factory: Optional factory to create instances. Generator factories
                (Generator[T, None, None] or AsyncGenerator[T, None]) are supported for
                resource cleanup - the container calls close()/aclose() when the scope exits.
            instance: Optional pre-created instance.
            lifetime: The lifetime of the service. This default applies only to explicit
                registrations via `register`; auto-registration uses
                `autoregister_default_lifetime` from container configuration.
            scope: Optional scope name for SCOPED services.
            is_async: Whether the factory is async. If None, auto-detected from factory.
            concrete_class: Optional concrete implementation class. When specified, `key`
                is used as the interface and `concrete_class` is the implementation.

        Returns:
            - When used as a bare decorator on a class: returns the class unchanged
            - When used as a parameterized decorator: returns a decorator function
            - When used as a direct call: returns None

        Raises:
            DIWireScopedWithoutScopeError: If lifetime is SCOPED but
                no scope is provided.
            DIWireConcreteClassRequiresClassError: If `concrete_class` is not a class type.
            DIWireDecoratorFactoryMissingReturnAnnotationError: If used as a factory decorator
                but the function has no return annotation and no explicit key.

        Note:
            When using generator factories for cleanup, wrap cleanup code in try/finally:

            .. code-block:: python

                def my_factory() -> Generator[Resource, None, None]:
                    resource = acquire_resource()
                    try:
                        yield resource
                    finally:
                        resource.close()  # MUST be in finally block

            Without try/finally, cleanup code after yield will not execute when the
            scope exits, as close()/aclose() raises GeneratorExit at the yield point.

        """
        # Check if all optional params are at defaults (for bare decorator detection)
        all_params_at_defaults = (
            factory is None
            and instance is None
            and lifetime == Lifetime.TRANSIENT
            and scope is None
            and is_async is None
            and concrete_class is None
        )

        # Case 1: Parameterized decorator without key - @container.register(lifetime=...)
        if key is None:
            return self._make_decorator(
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                interface_key=None,
            )

        # Case 2: Open generic decorator - @container.register(MyGeneric[T])
        if factory is None and instance is None and concrete_class is None:
            origin, args = _get_generic_origin_and_args(key)
            if origin is not None and any(_is_typevar(arg) for arg in args):
                return self._make_decorator(
                    lifetime=lifetime,
                    scope=scope,
                    is_async=is_async,
                    interface_key=key,
                )
            # Case 2b: Concrete generic alias - @container.register(MyGeneric[int])
            # This is a generic alias with all concrete type arguments (no TypeVars),
            # used as an interface key for registering a concrete class or factory.
            if origin is not None and args:
                return self._make_decorator(
                    lifetime=lifetime,
                    scope=scope,
                    is_async=is_async,
                    interface_key=key,
                )

        # Case 3+4 merged: Type as key (could be bare decorator, interface decorator, or factory)
        # Ambiguous case - we can't tell if this is:
        # - @container.register on class (bare decorator) -> should register and return class
        # - @container.register(Type) on function (factory) -> should register function as factory
        # - @container.register(Type) on class (interface) -> should register class under Type
        #
        # Solution: Create a proxy class that acts as both the original class and a decorator,
        # then register BOTH the original and proxy so resolution works with either key.
        if (
            isinstance(key, type)
            and factory is None
            and instance is None
            and concrete_class is None
        ):
            # Create a proxy class that inherits from original and can act as decorator
            proxy_class = self._make_class_proxy_decorator(
                original_class=key,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
            )
            # Register the proxy class (for decorator usage where proxy becomes the class)
            self._do_register(
                key=proxy_class,
                factory=None,
                instance=None,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                concrete_class=None,
            )
            # Also register the original class (for direct call usage)
            # This allows container.register(Type, ...) and container.resolve(Type) to work
            self._do_register(
                key=key,
                factory=None,
                instance=None,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                concrete_class=proxy_class,  # Use proxy as implementation
            )
            return proxy_class

        # Case 3: Bare decorator on a function - @container.register
        # Check that key is a proper function/method, not a generic alias like Annotated[T, ...]
        is_factory_function = (
            callable(key)
            and not isinstance(key, type)
            and get_origin(key) is None  # Not a generic alias
            and (
                inspect.isfunction(key) or inspect.ismethod(key) or inspect.iscoroutinefunction(key)
            )
        )
        if is_factory_function and all_params_at_defaults:
            service_type = _get_return_annotation(key)
            if service_type is None:
                raise DIWireDecoratorFactoryMissingReturnAnnotationError(key)
            self._do_register(
                key=service_type,
                factory=key,
                instance=None,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                concrete_class=None,
            )
            return key

        # Case 4: Bare decorator on a staticmethod - @staticmethod @container.register
        if _is_method_descriptor(key) and all_params_at_defaults:
            # _is_method_descriptor guarantees key is staticmethod,
            # so unwrapped_func is always non-None
            unwrapped_func, _ = _unwrap_method_descriptor(key)
            service_type = _get_return_annotation(unwrapped_func)  # type: ignore[arg-type]
            if service_type is None:
                raise DIWireDecoratorFactoryMissingReturnAnnotationError(unwrapped_func)
            # unwrapped_func is guaranteed non-None since _is_method_descriptor passed
            factory_func = cast("Callable[..., Any]", unwrapped_func)
            self._do_register(
                key=service_type,
                factory=factory_func,
                instance=None,
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                concrete_class=None,
            )
            return key

        # Case 5: Non-type key as decorator - @container.register("string_key")
        # This handles string keys or other hashable values used as service identifiers.
        # When key is not a type, function, method descriptor, or generic alias,
        # and no factory/instance/concrete_class is provided, return a decorator.
        if factory is None and instance is None and concrete_class is None:
            return self._make_decorator(
                lifetime=lifetime,
                scope=scope,
                is_async=is_async,
                interface_key=key,
            )

        # Case 6: Direct call - container.register(Interface, concrete_class=Impl)
        self._do_register(
            key=key,
            factory=factory,
            instance=instance,
            lifetime=lifetime,
            scope=scope,
            is_async=is_async,
            concrete_class=concrete_class,
        )
        return None

    def _make_class_proxy_decorator(
        self,
        original_class: type,
        lifetime: Lifetime,
        scope: str | None,
        is_async: bool | None,
    ) -> type:
        """Create a class proxy that works as both the original class and a decorator.

        This enables the ambiguous pattern where `@container.register(Type)` can be:
        - A bare decorator on the Type itself (returns the class)
        - A decorator factory for interface/factory registration (acts as decorator)

        The proxy inherits from the original class so isinstance/issubclass checks work,
        but its __new__ is overridden to handle decorator invocation.
        """
        container = self

        class _ClassProxyDecorator(original_class):  # type: ignore[valid-type, misc]
            """Proxy class that inherits from original and can act as a decorator.

            When instantiated with a type or callable (decorator pattern), it performs
            registration. Otherwise, it creates instances of the proxy class (not original)
            so isinstance checks work correctly.
            """

            # Store reference to avoid closure issues
            _original_class = original_class
            _lifetime = lifetime
            _scope = scope
            _is_async = is_async

            def __new__(cls, *args: Any, **kwargs: Any) -> Any:
                # Check if this is decorator invocation (single positional arg that's a type/callable)
                if len(args) == 1 and not kwargs:
                    target = args[0]
                    if isinstance(target, type):
                        if target is cls._original_class:
                            # Same class as interface key - just return it (already registered)
                            return target
                        # Interface registration: @proxy(ImplClass)
                        container._do_register(  # noqa: SLF001
                            key=cls._original_class,
                            factory=None,
                            instance=None,
                            lifetime=cls._lifetime,
                            scope=cls._scope,
                            is_async=cls._is_async,
                            concrete_class=target,
                        )
                        return target
                    if callable(target):
                        # Factory registration: @proxy(factory_func)
                        container._do_register(  # noqa: SLF001
                            key=cls._original_class,
                            factory=target,
                            instance=None,
                            lifetime=cls._lifetime,
                            scope=cls._scope,
                            is_async=cls._is_async,
                            concrete_class=None,
                        )
                        return target

                # Normal instantiation - create instance of THIS proxy class (not original)
                # so that isinstance(instance, proxy_class) returns True
                return object.__new__(cls)

            @classmethod
            def __class_getitem__(cls, item: Any) -> Any:
                """Forward generic subscripting to original class."""
                return original_class[item]  # type: ignore[index]

        # Preserve class metadata
        _ClassProxyDecorator.__name__ = original_class.__name__
        _ClassProxyDecorator.__qualname__ = original_class.__qualname__
        _ClassProxyDecorator.__module__ = original_class.__module__
        _ClassProxyDecorator.__doc__ = original_class.__doc__

        return _ClassProxyDecorator

    def _make_decorator(
        self,
        lifetime: Lifetime,
        scope: str | None,
        is_async: bool | None,
        interface_key: Any | None,
    ) -> Callable[[T], T]:
        """Create a decorator function for parameterized @container.register(...) usage.

        Args:
            lifetime: The lifetime of the service.
            scope: Optional scope name for SCOPED services.
            is_async: Whether the factory is async.
            interface_key: If provided, the decorated class/factory will be registered
                under this key (interface registration pattern).

        """

        def decorator(target: T) -> T:
            if isinstance(target, type):
                # Class decoration
                if interface_key is not None:  # pragma: no cover
                    # Interface registration: @container.register(Interface, ...) on a different class
                    # Note: This path is only reachable for open generics, but open generics
                    # with concrete_class raise DIWireOpenGenericRegistrationError, making
                    # this effectively unreachable. Kept for API completeness.
                    self._do_register(
                        key=interface_key,
                        factory=None,
                        instance=None,
                        lifetime=lifetime,
                        scope=scope,
                        is_async=is_async,
                        concrete_class=target,
                    )
                else:
                    # Regular class registration (interface_key is None)
                    self._do_register(
                        key=target,
                        factory=None,
                        instance=None,
                        lifetime=lifetime,
                        scope=scope,
                        is_async=is_async,
                        concrete_class=None,
                    )
            elif _is_method_descriptor(target):
                # staticmethod decoration
                # _is_method_descriptor guarantees target is staticmethod,
                # so unwrapped_func is always non-None
                unwrapped_func, _ = _unwrap_method_descriptor(target)
                service_type = interface_key
                if service_type is None:
                    service_type = _get_return_annotation(unwrapped_func)  # type: ignore[arg-type]
                    if service_type is None:
                        raise DIWireDecoratorFactoryMissingReturnAnnotationError(
                            unwrapped_func,
                        )
                # unwrapped_func is guaranteed non-None since _is_method_descriptor passed
                method_factory = cast("Callable[..., Any]", unwrapped_func)
                self._do_register(
                    key=service_type,
                    factory=method_factory,
                    instance=None,
                    lifetime=lifetime,
                    scope=scope,
                    is_async=is_async,
                    concrete_class=None,
                )
            else:
                # Factory function decoration - infer type from return annotation
                service_type = interface_key
                if service_type is None:
                    service_type = _get_return_annotation(target)  # type: ignore[arg-type]
                    if service_type is None:
                        raise DIWireDecoratorFactoryMissingReturnAnnotationError(target)
                self._do_register(
                    key=service_type,
                    factory=target,
                    instance=None,
                    lifetime=lifetime,
                    scope=scope,
                    is_async=is_async,
                    concrete_class=None,
                )
            return target

        return decorator

    def _get_open_generic_info_for_registration(
        self,
        service_key: ServiceKey,
    ) -> tuple[type, tuple[Any, ...]] | None:
        origin, args = _get_generic_origin_and_args(service_key.value)
        if origin is None or not args:
            return None
        if not any(_is_typevar(arg) for arg in args):
            return None
        if not all(_is_typevar(arg) for arg in args):
            raise DIWireOpenGenericRegistrationError(
                service_key,
                "Open generic registrations must use only TypeVar parameters.",
            )
        return origin, tuple(args)

    def _register_open_generic(
        self,
        *,
        origin: type,
        service_key: ServiceKey,
        registration: Registration,
        typevars: tuple[Any, ...],
    ) -> None:
        entry = _OpenGenericRegistration(
            service_key=service_key,
            registration=registration,
            typevars=typevars,
        )
        if registration.scope is not None:
            self._scoped_open_generic_registry[
                (origin, service_key.component, registration.scope)
            ] = entry
            self._has_scoped_registrations = True
        else:
            self._open_generic_registry[(origin, service_key.component)] = entry

    def _do_register(
        self,
        key: Any,
        factory: Factory | None,
        instance: Any | None,
        lifetime: Lifetime,
        scope: str | None,
        is_async: bool | None,
        concrete_class: type | None,
    ) -> None:
        """Perform the actual registration logic."""
        # Determine service_key and concrete_type based on concrete_class parameter
        if concrete_class is not None:
            # Interface registration: key is the interface, concrete_class is the implementation
            if not isinstance(concrete_class, type):
                raise DIWireConcreteClassRequiresClassError(concrete_class)
            service_key = ServiceKey.from_value(key)
            concrete_type: type | None = concrete_class
        else:
            service_key = ServiceKey.from_value(key)
            concrete_type = key if isinstance(key, type) else None

        if lifetime == Lifetime.SCOPED and scope is None:
            raise DIWireScopedWithoutScopeError(service_key)

        # Auto-detect if factory is async when not explicitly specified
        detected_is_async = False
        if is_async is not None:
            detected_is_async = is_async
        elif factory is not None:
            detected_is_async = _is_async_factory(factory)

        open_generic_info = self._get_open_generic_info_for_registration(service_key)
        if open_generic_info is not None:
            if concrete_class is not None:
                raise DIWireOpenGenericRegistrationError(
                    service_key,
                    "Open generic registrations with 'concrete_class' are not supported.",
                )
            if instance is not None:
                raise DIWireOpenGenericRegistrationError(
                    service_key,
                    "Open generic registrations do not support instances.",
                )
            origin, typevars = open_generic_info
            registration = Registration(
                service_key=service_key,
                factory=factory,
                instance=instance,
                lifetime=lifetime,
                scope=scope,
                is_async=detected_is_async,
                concrete_type=concrete_type,
                typevar_map=None,
            )
            self._register_open_generic(
                origin=origin,
                service_key=service_key,
                registration=registration,
                typevars=typevars,
            )
            # Track scoped registrations
            if lifetime == Lifetime.SCOPED:
                self._has_scoped_registrations = True
            self._is_compiled = False
            return

        registration = Registration(
            service_key=service_key,
            factory=factory,
            instance=instance,
            lifetime=lifetime,
            scope=scope,
            is_async=detected_is_async,
            concrete_type=concrete_type,
        )

        # If registering with an instance (non-scoped), update the singleton cache immediately
        # This ensures re-registration overwrites any previously cached value
        if instance is not None and scope is None:
            self._singletons[service_key] = instance
            # Also clear type cache for re-registration
            if isinstance(service_key.value, type) and service_key.component is None:
                self._type_singletons[service_key.value] = instance

        if scope is not None:
            # Store in scoped registry for scope-specific lookup
            self._scoped_registry[(service_key, scope)] = registration
            # Track that we have scoped registrations
            self._has_scoped_registrations = True
        else:
            # Store in global registry
            self._registry[service_key] = registration

        # Track scoped singleton registrations
        if lifetime == Lifetime.SCOPED:
            self._has_scoped_registrations = True

        # Invalidate compiled state when registrations change
        self._is_compiled = False

    def enter_scope(self, scope_name: str | None = None) -> ScopedContainer:
        """Start a new scope for resolving SCOPED dependencies.

        The scope is activated immediately upon creation, allowing imperative usage:
            scope = container.enter_scope("request")
            # ... use the scope ...
            scope.close()  # or container.close() to close all scopes

        Context manager usage is also supported:
            with container.enter_scope("request") as scope:
                # ... use the scope ...

        Args:
            scope_name: Optional name for the scope. If not provided, an integer ID is generated.

        Returns:
            A ScopedContainer that is already activated.

        Note:
            Nested scopes inherit from parent scopes. A scope started within
            another scope will have access to dependencies registered for the
            parent scope.

        """
        self._check_not_closed()

        # Generate unique instance ID for each scope (integer is faster than UUID)
        instance_id = next(self._scope_counter)

        # Create new segment as tuple
        new_segment = (scope_name, instance_id)

        # Build scope by appending to current scope's segments
        current = _current_scope.get()
        segments = (*current.segments, new_segment) if current is not None else (new_segment,)

        scope_id = _ScopeId(segments=segments)
        return ScopedContainer(_container=self, _scope_id=scope_id)

    def _clear_scope(self, scope_id: _ScopeId) -> None:
        """Clear cached instances for a scope.

        Args:
            scope_id: The scope ID to clear.

        """
        scope_key = scope_id.segments
        scope_exit_stack = self._scope_exit_stacks.pop(scope_key, None)
        if scope_exit_stack is not None:
            scope_exit_stack.close()

        # Close async exit stack (if any async generators were resolved in this scope)
        # Peek first without removing - only remove after successfully scheduling cleanup
        async_exit_stack = self._async_scope_exit_stacks.get(scope_key)
        if async_exit_stack is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running event loop - leave stack in place for later _aclear_scope() call
                scope_name = scope_key[-1][0] if scope_key else None
                raise DIWireAsyncCleanupWithoutEventLoopError(scope_name) from None
            # Event loop is running - schedule cleanup as a task
            task = loop.create_task(async_exit_stack.aclose())
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)
            # Only remove after successfully scheduling cleanup
            del self._async_scope_exit_stacks[scope_key]

        # Remove all scoped instances with keys starting with this scope
        # Snapshot keys to avoid RuntimeError from dict mutation during iteration
        keys_to_remove = [k for k in list(self._scoped_instances) if k[0] == scope_key]
        for k in keys_to_remove:
            del self._scoped_instances[k]
        self._locks.clear_scope_locks(scope_key)

    def _get_scope_exit_stack(
        self,
        scope_key: tuple[tuple[str | None, int], ...],
    ) -> ExitStack:
        scope_exit_stack = self._scope_exit_stacks.get(scope_key)
        if scope_exit_stack is None:
            scope_exit_stack = ExitStack()
            self._scope_exit_stacks[scope_key] = scope_exit_stack
        return scope_exit_stack

    def compile(self) -> None:
        """Compile all registered services into optimized providers.

        This pre-compiles the dependency graph into specialized provider objects
        that eliminate runtime reflection and minimize dict lookups. Call this
        after all services have been registered for maximum performance.
        """
        self._compiled_providers.clear()
        self._scoped_compiled_providers.clear()
        self._type_providers.clear()
        self._type_singletons.clear()
        self._async_deps_cache.clear()

        # Iterate over a copy since _compile_or_get_provider may add to registry
        for service_key, registration in list(self._registry.items()):
            provider = self._compile_registration(service_key, registration)
            if provider is not None:
                self._compiled_providers[service_key] = provider

        # Compile scoped registrations
        for (service_key, scope_name), registration in list(self._scoped_registry.items()):
            provider = self._compile_scoped_registration(service_key, registration, scope_name)
            if provider is not None:
                self._scoped_compiled_providers[(service_key, scope_name)] = provider

        # Build async dependency cache for faster async resolution
        self._build_async_deps_cache()

        # Pre-warm fast type caches for direct type lookups
        for service_key, provider in list(self._compiled_providers.items()):
            if isinstance(service_key.value, type) and service_key.component is None:
                self._type_providers[service_key.value] = provider
                # Also cache any already-resolved singletons
                if service_key in self._singletons:
                    self._type_singletons[service_key.value] = self._singletons[service_key]

        self._is_compiled = True

    def _build_async_deps_cache(self) -> None:
        """Build a cache of which service keys have async dependencies.

        This eliminates registry lookups in the async resolution path.
        """
        for service_key in list(self._registry):
            if not isinstance(service_key.value, type):
                continue

            async_deps: set[ServiceKey] = set()
            try:
                deps = self._dependencies_extractor.get_dependencies_with_defaults(service_key)
                for param_info in deps.values():
                    if param_info.typevar is not None:
                        continue
                    dep_reg = self._registry.get(param_info.service_key)
                    if dep_reg is not None and dep_reg.is_async:
                        async_deps.add(param_info.service_key)
            except DIWireError:
                continue

            if async_deps:
                self._async_deps_cache[service_key] = frozenset(async_deps)

    def _compile_registration(
        self,
        service_key: ServiceKey,
        registration: Registration,
    ) -> CompiledProvider | None:
        """Compile a single registration into an optimized provider."""
        # Skip scoped registrations (handled separately)
        if registration.scope is not None:
            return None
        if registration.is_async:
            return None
        if registration.typevar_map is not None:
            return None

        # Handle pre-created instances
        if registration.instance is not None:
            return InstanceProvider(registration.instance)

        # Handle factory registrations
        if registration.factory is not None:
            if isinstance(registration.factory, type):
                # Factory is a class - compile it as a provider
                factory_key = ServiceKey.from_value(registration.factory)
                factory_provider = self._compile_or_get_provider(factory_key)
                if factory_provider is None:
                    return None
            elif isinstance(registration.factory, FunctionType | MethodType):
                # Functions/methods need resolution - skip compilation for now
                # They may have Injected parameters that need injection
                return None
            else:
                # Factory is a built-in callable (e.g., ContextVar.get) - wrap directly
                factory_provider = InstanceProvider(registration.factory)
            result_handler = self._make_compiled_factory_result_handler(
                service_key,
                registration.lifetime,
                registration.scope,
            )
            if registration.lifetime == Lifetime.SINGLETON:
                return SingletonFactoryProvider(service_key, factory_provider, result_handler)
            return FactoryProvider(factory_provider, result_handler)

        # Use concrete_type if registered with provides parameter
        instantiation_type = registration.concrete_type or service_key.value

        # Handle type registrations - compile dependencies
        if not isinstance(instantiation_type, type):
            return None

        # Use concrete type's service key for dependency extraction
        instantiation_key = (
            ServiceKey.from_value(instantiation_type)
            if registration.concrete_type is not None
            else service_key
        )

        try:
            deps = self._dependencies_extractor.get_dependencies_with_defaults(instantiation_key)
        except DIWireError:
            return None

        # Filter out ignored types with defaults
        filtered_deps: dict[str, ServiceKey] = {}
        for name, param_info in deps.items():
            if param_info.typevar is not None:
                return None
            if param_info.service_key.value in self._autoregister_ignores:
                if param_info.has_default:
                    continue
                # Can't compile - missing required dependency
                return None
            filtered_deps[name] = param_info.service_key

        if not filtered_deps:
            # No dependencies - use simple provider
            if registration.lifetime == Lifetime.SINGLETON:
                return SingletonTypeProvider(instantiation_type, service_key)
            return TypeProvider(instantiation_type)

        # Compile dependency providers
        param_names: list[str] = []
        dep_providers: list[CompiledProvider] = []
        for name, dep_key in filtered_deps.items():
            dep_provider = self._compile_or_get_provider(dep_key)
            if dep_provider is None:
                return None
            param_names.append(name)
            dep_providers.append(dep_provider)

        if registration.lifetime == Lifetime.SINGLETON:
            return SingletonArgsTypeProvider(
                instantiation_type,
                service_key,
                tuple(param_names),
                tuple(dep_providers),
            )
        return ArgsTypeProvider(
            instantiation_type,
            tuple(param_names),
            tuple(dep_providers),
        )

    def _make_compiled_factory_result_handler(
        self,
        service_key: ServiceKey,
        lifetime: Lifetime,
        scope: str | None,
    ) -> Callable[[Any], Any]:
        def handler(result: Any) -> Any:
            return self._handle_compiled_factory_result(
                result,
                service_key,
                lifetime,
                scope,
            )

        return handler

    def _handle_compiled_factory_result(
        self,
        result: Any,
        service_key: ServiceKey,
        lifetime: Lifetime,
        scope: str | None,
    ) -> Any:
        if inspect.iscoroutine(result):
            result.close()
            raise DIWireAsyncDependencyInSyncContextError(service_key, service_key)
        if isinstance(result, AsyncGenerator):
            raise DIWireAsyncDependencyInSyncContextError(service_key, service_key)
        if isinstance(result, Generator):
            current_scope = _current_scope.get() if self._has_scoped_registrations else None
            cache_scope = self._get_cache_scope(current_scope, scope)
            if cache_scope is None:
                raise DIWireGeneratorFactoryWithoutScopeError(service_key)
            if lifetime == Lifetime.SINGLETON:
                raise DIWireGeneratorFactoryUnsupportedLifetimeError(service_key)
            try:
                instance = next(result)
            except StopIteration as exc:
                raise DIWireGeneratorFactoryDidNotYieldError(service_key) from exc
            self._get_scope_exit_stack(cache_scope).callback(result.close)
            return instance
        return result

    def _compile_or_get_provider(self, service_key: ServiceKey) -> CompiledProvider | None:
        """Get an existing compiled provider or compile a new one."""
        # Check if already compiled
        if service_key in self._compiled_providers:
            return self._compiled_providers[service_key]

        # Check registry
        registration = self._registry.get(service_key)
        if registration is not None:
            provider = self._compile_registration(service_key, registration)
            if provider is not None:
                self._compiled_providers[service_key] = provider
            return provider

        # Auto-register if enabled
        if self._autoregister:
            try:
                registration = self._get_auto_registration(service_key)
                self._registry[service_key] = registration
                provider = self._compile_registration(service_key, registration)
                if provider is not None:
                    self._compiled_providers[service_key] = provider
                return provider
            except DIWireError:
                return None

        return None

    def _compile_scoped_registration(
        self,
        service_key: ServiceKey,
        registration: Registration,
        _scope_name: str,
    ) -> CompiledProvider | None:
        """Compile a scoped registration into an optimized provider.

        Uses ScopedSingletonProvider for scoped singletons.
        """
        # Skip non-type registrations (instances, factories)
        # These need special handling for scope lifecycle
        if registration.instance is not None or registration.factory is not None:
            return None
        if registration.typevar_map is not None:
            return None

        # Use concrete_type if registered with provides parameter
        instantiation_type = registration.concrete_type or service_key.value

        if not isinstance(instantiation_type, type):
            return None

        # Use concrete type's service key for dependency extraction
        instantiation_key = (
            ServiceKey.from_value(instantiation_type)
            if registration.concrete_type is not None
            else service_key
        )

        try:
            deps = self._dependencies_extractor.get_dependencies_with_defaults(instantiation_key)
        except DIWireError:
            return None

        # Filter out ignored types with defaults
        filtered_deps: dict[str, ServiceKey] = {}
        for name, param_info in deps.items():
            if param_info.typevar is not None:
                return None
            if param_info.service_key.value in self._autoregister_ignores:
                if param_info.has_default:
                    continue
                return None
            filtered_deps[name] = param_info.service_key

        if not filtered_deps:
            # No dependencies - use simple scoped provider
            return ScopedSingletonProvider(instantiation_type, service_key)

        # Skip compilation when any dependency has a scoped registration.
        if self._scoped_registry:
            scoped_service_keys = {scoped_key for scoped_key, _ in self._scoped_registry}
            if any(dep_key in scoped_service_keys for dep_key in filtered_deps.values()):
                return None

        # Compile dependency providers
        param_names: list[str] = []
        dep_providers: list[CompiledProvider] = []
        for name, dep_key in filtered_deps.items():
            dep_provider = self._compile_or_get_provider(dep_key)
            if dep_provider is None:
                return None
            param_names.append(name)
            dep_providers.append(dep_provider)

        return ScopedSingletonArgsProvider(
            instantiation_type,
            service_key,
            tuple(param_names),
            tuple(dep_providers),
        )

    # Decorator overloads (key=None) - returns a decorator that wraps functions
    @overload
    def resolve(
        self,
        key: None = None,
        *,
        scope: str,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    @overload
    def resolve(
        self,
        key: None = None,
        *,
        scope: None = None,
    ) -> Callable[[Callable[..., Any]], Any]: ...

    @overload
    def resolve(self, key: type[T], *, scope: None = None) -> T: ...

    @overload
    def resolve(self, key: type[T], *, scope: str) -> T: ...

    @overload
    def resolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: None = None,
    ) -> _AsyncInjectedFunction[T]: ...

    @overload
    def resolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: str,
    ) -> _AsyncScopedInjectedFunction[T]: ...

    @overload
    def resolve(self, key: Callable[..., T], *, scope: None = None) -> _InjectedFunction[T]: ...

    @overload
    def resolve(self, key: Callable[..., T], *, scope: str) -> _ScopedInjectedFunction[T]: ...

    @overload
    def resolve(self, key: ServiceKey, *, scope: str | None = None) -> Any: ...

    @overload
    def resolve(self, key: Any, *, scope: str | None = None) -> Any: ...

    def resolve(self, key: Any | None = None, *, scope: str | None = None) -> Any:  # noqa: PLR0915
        """Resolve and return a service instance by its key.

        When called with key=None, returns a decorator that can be applied to
        functions to enable dependency injection.

        Args:
            key: The service key to resolve. If None, returns a decorator.
            scope: Optional scope name. If provided and key is a function,
                   returns a ScopedInjected that creates a new scope per call.

        Examples:
            # Direct usage:
            injected = container.resolve(my_func, scope="request")

            # Decorator usage:
            @container.resolve(scope="request")
            async def handler(service: Annotated[Service, Injected()]) -> dict:
                ...

        """
        self._check_not_closed()

        # DECORATOR PATTERN: resolve(scope="...") or resolve() returns decorator
        if key is None:

            def decorator(func: Callable[..., Any]) -> Any:
                return self.resolve(func, scope=scope)

            return decorator

        # FAST PATH for simple types (most common case)
        # Bypasses ServiceKey creation entirely for cached singletons
        # Only use fast path when not in a scope (scoped registrations may override)
        if (
            isinstance(key, type)
            and scope is None
            and (not self._has_scoped_registrations or _current_scope.get() is None)
        ):
            # Direct singleton lookup - fastest path
            cached = self._type_singletons.get(key)
            if cached is not None:
                return cached

            # Direct provider lookup (only when compiled)
            if self._is_compiled:
                provider = self._type_providers.get(key)
                if provider is not None:
                    result = provider(self._singletons, None)
                    # Cache singleton results for next time (singleton providers have _instance)
                    if hasattr(provider, "_instance"):
                        self._type_singletons[key] = result
                    return result

        service_key = ServiceKey.from_value(key)
        if isinstance(service_key.value, FunctionType | MethodType):
            # Determine scope: explicit parameter takes precedence
            # If scope is None, try to detect from dependencies (may fail with NameError
            # if using `from __future__ import annotations` with forward references)
            effective_scope = scope
            if effective_scope is None:
                try:
                    injected_deps = self._dependencies_extractor.get_injected_dependencies(
                        service_key=service_key,
                    )
                    effective_scope = self._find_scope_in_dependencies(injected_deps)
                except NameError:
                    # Forward reference not resolvable yet (e.g., with PEP 563)
                    # Default to no scope - user should provide explicit scope parameter
                    effective_scope = None

            # Check if the function is async
            is_async_func = inspect.iscoroutinefunction(service_key.value)

            if effective_scope is not None:
                if is_async_func:
                    return _AsyncScopedInjectedFunction(
                        func=service_key.value,
                        container=self,
                        dependencies_extractor=self._dependencies_extractor,
                        service_key=service_key,
                        scope_name=effective_scope,
                    )
                return _ScopedInjectedFunction(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                    scope_name=effective_scope,
                )
            if is_async_func:
                return _AsyncInjectedFunction(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                )
            return _InjectedFunction(
                func=service_key.value,
                container=self,
                dependencies_extractor=self._dependencies_extractor,
                service_key=service_key,
            )

        # Skip ContextVar lookup when no scoped registrations exist
        current_scope = _current_scope.get() if self._has_scoped_registrations else None

        # Auto-compile on first resolve if enabled and not in a scope
        if self._auto_compile and not self._is_compiled and current_scope is None:
            self.compile()

        # Fast path: use compiled providers when available and not in a scope
        if self._is_compiled and current_scope is None:
            provider = self._compiled_providers.get(service_key)
            if provider is not None:
                return provider(self._singletons, None)

        # Check for scoped registration FIRST when inside a scope
        scoped_registration = None
        scoped_scope_name: str | None = None
        if current_scope is not None:
            scoped_registration = self._get_scoped_registration(service_key, current_scope)
            if scoped_registration is not None:
                scoped_scope_name = scoped_registration.scope

        # Return cached global singleton ONLY if no scoped registration matches
        if scoped_registration is None and service_key in self._singletons:
            return self._singletons[service_key]

        # Fast path for compiled scoped providers
        if (
            self._is_compiled
            and scoped_registration is not None
            and scoped_scope_name is not None
            and current_scope is not None
        ):
            scoped_provider = self._scoped_compiled_providers.get((service_key, scoped_scope_name))
            if scoped_provider is not None:
                # Transient: no caching, create new instance each time
                if scoped_registration.lifetime == Lifetime.TRANSIENT:
                    return scoped_provider(self._singletons, None)

                # Scoped singleton: use cache
                cache_scope = current_scope.get_cache_key_for_scope(scoped_scope_name)
                if cache_scope is not None:
                    cache_key = (cache_scope, service_key)
                    # Check cache first
                    cached = self._scoped_instances.get(cache_key)
                    if cached is not None:
                        return cached
                    scoped_lock = self._locks.get_sync_scoped_singleton_lock(cache_key)
                    with scoped_lock:
                        cached = self._scoped_instances.get(cache_key)
                        if cached is not None:  # pragma: no cover - race timing dependent
                            return cached  # pragma: no cover - race timing dependent
                        # Use compiled provider (pass None - we handle caching at container level)
                        result = scoped_provider(self._singletons, None)
                        # Store directly in flat cache
                        self._scoped_instances[cache_key] = result
                        return result

        # Inline circular dependency tracking (avoids context manager overhead)
        stack = _get_resolution_stack()
        if service_key in stack:
            raise DIWireCircularDependencyError(service_key, list(stack))
        stack.append(service_key)

        try:
            # Use scoped registration if found, otherwise get from registry
            registration = (
                scoped_registration
                if scoped_registration is not None
                else self._get_registration(service_key, current_scope)
            )

            # Validate scope if service is registered with a specific scope
            if registration.scope is not None and (
                current_scope is None or not self._scope_matches(current_scope, registration.scope)
            ):
                raise DIWireScopeMismatchError(
                    service_key,
                    registration.scope,
                    current_scope.path if current_scope else None,
                )

            # Check for async dependencies - raise early with helpful error
            if registration.is_async:
                raise DIWireAsyncDependencyInSyncContextError(service_key, service_key)

            # Determine the scope key to use for caching
            cache_scope = self._get_cache_scope(current_scope, registration.scope)
            cache_key = (cache_scope, service_key) if cache_scope is not None else None  # type: ignore[assignment]

            # Check scoped instance cache using flat dict (single lookup)
            if cache_key is not None:
                cached = self._scoped_instances.get(cache_key)
                if cached is not None:
                    return cached

            scoped_lock: threading.Lock | None = None  # type: ignore[no-redef]
            if (
                registration.lifetime == Lifetime.SCOPED
                and cache_key is not None  # type: ignore[redundant-expr]
                and registration.instance is None
            ):
                scoped_lock = self._locks.get_sync_scoped_singleton_lock(cache_key)
                scoped_lock.acquire()
                # Double-check cache after acquiring lock
                cached = self._scoped_instances.get(cache_key)
                if cached is not None:  # pragma: no cover - race timing dependent
                    scoped_lock.release()  # pragma: no cover
                    return cached  # pragma: no cover

            if registration.instance is not None:
                # Cache scoped instances in _scoped_instances, not _singletons
                if registration.scope is not None and cache_key is not None:
                    self._scoped_instances[cache_key] = registration.instance
                else:
                    self._singletons[service_key] = registration.instance
                if scoped_lock is not None and scoped_lock.locked():  # type: ignore[redundant-expr] # pragma: no cover - defensive, lock only acquired when instance is None
                    scoped_lock.release()  # pragma: no cover
                return registration.instance

            # For singletons, use lock to prevent race conditions in threaded resolution
            is_global_singleton = (
                registration.lifetime == Lifetime.SINGLETON and scoped_registration is None
            )
            singleton_lock: threading.Lock | None = None

            if is_global_singleton:
                singleton_lock = self._locks.get_sync_singleton_lock(service_key)
                singleton_lock.acquire()
                # Double-check: re-check cache after acquiring lock
                if service_key in self._singletons:
                    singleton_lock.release()
                    return self._singletons[service_key]

            try:
                if registration.factory is not None:
                    if isinstance(registration.factory, type):
                        # Factory is a class - resolve via container to instantiate
                        factory: Any = self.resolve(registration.factory)
                        instance = factory()
                    elif isinstance(registration.factory, FunctionType | MethodType):
                        # Function/method factory - resolve ALL deps and call directly
                        # This allows factory functions to have all params auto-injected
                        factory_key = ServiceKey.from_value(registration.factory)
                        resolved = self._get_resolved_dependencies(
                            factory_key,
                            typevar_map=registration.typevar_map,
                        )
                        if resolved.missing:
                            raise DIWireMissingDependenciesError(factory_key, resolved.missing)
                        instance = registration.factory(**resolved.dependencies)
                    else:
                        # Factory is a built-in callable (e.g., ContextVar.get) - use directly
                        instance = registration.factory()
                    if isinstance(instance, Generator):
                        if cache_scope is None:
                            raise DIWireGeneratorFactoryWithoutScopeError(service_key)
                        if registration.lifetime == Lifetime.SINGLETON:
                            raise DIWireGeneratorFactoryUnsupportedLifetimeError(service_key)
                        try:
                            generated_instance = next(instance)
                        except StopIteration as exc:
                            raise DIWireGeneratorFactoryDidNotYieldError(service_key) from exc
                        self._get_scope_exit_stack(cache_scope).callback(instance.close)
                        instance = generated_instance  # type: ignore[possibly-undefined]

                    if registration.lifetime == Lifetime.SINGLETON:
                        self._singletons[service_key] = instance
                    elif registration.lifetime == Lifetime.SCOPED and cache_key is not None:
                        self._scoped_instances[cache_key] = instance

                    return instance

                # Use concrete_type if registered with provides parameter
                instantiation_type = registration.concrete_type or service_key.value
                instantiation_key = (
                    ServiceKey.from_value(instantiation_type)
                    if registration.concrete_type is not None
                    else service_key
                )

                resolved_dependencies = self._get_resolved_dependencies(
                    service_key=instantiation_key,
                    typevar_map=registration.typevar_map,
                )
                if resolved_dependencies.missing:
                    raise DIWireMissingDependenciesError(service_key, resolved_dependencies.missing)

                instance = instantiation_type(**resolved_dependencies.dependencies)

                if registration.lifetime == Lifetime.SINGLETON:
                    self._singletons[service_key] = instance
                elif registration.lifetime == Lifetime.SCOPED and cache_key is not None:
                    self._scoped_instances[cache_key] = instance

                return instance
            finally:
                if singleton_lock is not None and singleton_lock.locked():
                    singleton_lock.release()
                if scoped_lock is not None and scoped_lock.locked():  # type: ignore[redundant-expr]
                    scoped_lock.release()
        finally:
            stack.pop()

    @overload
    async def aresolve(self, key: type[T], *, scope: None = None) -> T: ...

    @overload
    async def aresolve(self, key: type[T], *, scope: str) -> T: ...

    @overload
    async def aresolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: None = None,
    ) -> _AsyncInjectedFunction[T]: ...

    @overload
    async def aresolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: str,
    ) -> _AsyncScopedInjectedFunction[T]: ...

    @overload
    async def aresolve(self, key: ServiceKey, *, scope: str | None = None) -> Any: ...

    @overload
    async def aresolve(self, key: Any, *, scope: str | None = None) -> Any: ...

    async def aresolve(self, key: Any, *, scope: str | None = None) -> Any:  # noqa: PLR0915
        """Asynchronously resolve and return a service instance by its key.

        This method supports async factories and async generator factories.
        Use this method when resolving services that have async dependencies.

        Note:
            For decorator usage, use the synchronous `.resolve()` method which
            handles both sync and async functions correctly.

        Args:
            key: The service key to resolve.
            scope: Optional scope name. If provided and key is a function,
                   returns an AsyncScopedInjected that creates a new scope per call.

        Raises:
            DIWireAsyncGeneratorFactoryWithoutScopeError: If an async generator factory
                is used without an active scope.

        Examples:
            # Direct usage:
            injected = await container.aresolve(my_func, scope="request")

        """
        self._check_not_closed()

        # FAST PATH for cached singletons (same as sync resolve)
        # Only use fast path when not in a scope (scoped registrations may override)
        if (
            isinstance(key, type)
            and scope is None
            and (not self._has_scoped_registrations or _current_scope.get() is None)
        ):
            cached = self._type_singletons.get(key)
            if cached is not None:
                return cached

        service_key = ServiceKey.from_value(key)
        if isinstance(service_key.value, FunctionType | MethodType):
            # Determine scope: explicit parameter takes precedence
            # If scope is None, try to detect from dependencies (may fail with NameError
            # if using `from __future__ import annotations` with forward references)
            effective_scope = scope
            if effective_scope is None:
                try:
                    injected_deps = self._dependencies_extractor.get_injected_dependencies(
                        service_key=service_key,
                    )
                    effective_scope = self._find_scope_in_dependencies(injected_deps)
                except NameError:
                    # Forward reference not resolvable yet (e.g., with PEP 563)
                    # Default to no scope - user should provide explicit scope parameter
                    effective_scope = None

            # Check if the function is async
            is_async_func = inspect.iscoroutinefunction(service_key.value)

            if effective_scope is not None:
                if is_async_func:
                    return _AsyncScopedInjectedFunction(
                        func=service_key.value,
                        container=self,
                        dependencies_extractor=self._dependencies_extractor,
                        service_key=service_key,
                        scope_name=effective_scope,
                    )
                return _ScopedInjectedFunction(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                    scope_name=effective_scope,
                )
            if is_async_func:
                return _AsyncInjectedFunction(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                )
            return _InjectedFunction(
                func=service_key.value,
                container=self,
                dependencies_extractor=self._dependencies_extractor,
                service_key=service_key,
            )

        # Skip ContextVar lookup when no scoped registrations exist
        current_scope = _current_scope.get() if self._has_scoped_registrations else None

        # Auto-compile on first resolve if enabled and not in a scope
        if self._auto_compile and not self._is_compiled and current_scope is None:
            self.compile()

        # Return cached global singleton if available and no scoped registration
        scoped_registration = None
        if current_scope is not None:
            scoped_registration = self._get_scoped_registration(service_key, current_scope)

        if scoped_registration is None and service_key in self._singletons:
            return self._singletons[service_key]

        # Inline circular dependency tracking
        stack = _get_resolution_stack()
        if service_key in stack:
            raise DIWireCircularDependencyError(service_key, list(stack))
        stack.append(service_key)

        try:
            # Use scoped registration if found, otherwise get from registry
            registration = (
                scoped_registration
                if scoped_registration is not None
                else self._get_registration(service_key, current_scope)
            )

            # Validate scope if service is registered with a specific scope
            if registration.scope is not None and (
                current_scope is None or not self._scope_matches(current_scope, registration.scope)
            ):
                raise DIWireScopeMismatchError(
                    service_key,
                    registration.scope,
                    current_scope.path if current_scope else None,
                )

            # Determine the scope key to use for caching
            cache_scope = self._get_cache_scope(current_scope, registration.scope)
            cache_key = (cache_scope, service_key) if cache_scope is not None else None

            # Check scoped instance cache using flat dict (single lookup)
            if cache_key is not None:
                cached = self._scoped_instances.get(cache_key)
                if cached is not None:
                    return cached

            scoped_lock: asyncio.Lock | None = None
            if (
                registration.lifetime == Lifetime.SCOPED
                and cache_key is not None
                and registration.instance is None
            ):
                scoped_lock = await self._locks.get_scoped_singleton_lock(cache_key)
                await scoped_lock.acquire()
                # Double-check cache after acquiring lock
                cached = self._scoped_instances.get(cache_key)
                if cached is not None:
                    scoped_lock.release()
                    return cached

            if registration.instance is not None:
                if registration.scope is not None and cache_key is not None:
                    self._scoped_instances[cache_key] = registration.instance
                else:
                    self._singletons[service_key] = registration.instance
                if (
                    scoped_lock is not None and scoped_lock.locked()
                ):  # pragma: no cover - defensive, lock only acquired when instance is None
                    scoped_lock.release()  # pragma: no cover
                return registration.instance

            # For singletons, use lock to prevent race conditions in async resolution
            # The lock is acquired here (after getting registration) and released in finally
            is_global_singleton = (
                registration.lifetime == Lifetime.SINGLETON and scoped_registration is None
            )
            singleton_lock: asyncio.Lock | None = None

            if is_global_singleton:
                singleton_lock = await self._locks.get_singleton_lock(service_key)
                await singleton_lock.acquire()
                # Double-check: re-check cache after acquiring lock
                # This path is hit when another coroutine resolved while we were waiting for the lock
                if service_key in self._singletons:  # pragma: no cover - race timing dependent
                    singleton_lock.release()
                    return self._singletons[service_key]

            try:
                if registration.factory is not None:
                    # Call the factory based on its type
                    if isinstance(registration.factory, type):
                        # Factory is a class - resolve via container to instantiate
                        factory: Any = await self.aresolve(registration.factory)
                        result = factory()
                    elif isinstance(registration.factory, FunctionType | MethodType):
                        # Function/method factory - resolve ALL deps and call directly
                        # This allows factory functions to have all params auto-injected
                        factory_key = ServiceKey.from_value(registration.factory)
                        resolved = await self._aget_resolved_dependencies(
                            factory_key,
                            typevar_map=registration.typevar_map,
                        )
                        if resolved.missing:
                            raise DIWireMissingDependenciesError(factory_key, resolved.missing)
                        result = registration.factory(**resolved.dependencies)
                    else:
                        # Factory is a built-in callable (e.g., ContextVar.get) - use directly
                        result = registration.factory()

                    # Handle async factories
                    if inspect.iscoroutine(result):
                        instance = await result
                    elif isinstance(result, AsyncGenerator):
                        # Async generator factory
                        if cache_scope is None:
                            raise DIWireAsyncGeneratorFactoryWithoutScopeError(service_key)
                        if registration.lifetime == Lifetime.SINGLETON:
                            raise DIWireGeneratorFactoryUnsupportedLifetimeError(service_key)
                        try:
                            instance = await result.__anext__()
                        except StopAsyncIteration as exc:
                            raise DIWireAsyncGeneratorFactoryDidNotYieldError(service_key) from exc
                        # Register cleanup
                        async_exit_stack = self._get_async_scope_exit_stack(cache_scope)
                        async_exit_stack.push_async_callback(result.aclose)
                    elif isinstance(result, Generator):
                        # Sync generator factory
                        if cache_scope is None:
                            raise DIWireGeneratorFactoryWithoutScopeError(service_key)
                        if registration.lifetime == Lifetime.SINGLETON:
                            raise DIWireGeneratorFactoryUnsupportedLifetimeError(service_key)
                        try:
                            instance = next(result)
                        except StopIteration as exc:
                            raise DIWireGeneratorFactoryDidNotYieldError(service_key) from exc
                        self._get_scope_exit_stack(cache_scope).callback(result.close)
                    else:
                        instance = result

                    if registration.lifetime == Lifetime.SINGLETON:
                        self._singletons[service_key] = instance  # type: ignore[possibly-undefined]
                    elif registration.lifetime == Lifetime.SCOPED and cache_key is not None:
                        self._scoped_instances[cache_key] = instance  # type: ignore[possibly-undefined]

                    return instance  # type: ignore[possibly-undefined]

                # Use concrete_type if registered with provides parameter
                instantiation_type = registration.concrete_type or service_key.value
                instantiation_key = (
                    ServiceKey.from_value(instantiation_type)
                    if registration.concrete_type is not None
                    else service_key
                )

                # Resolve dependencies
                resolved_dependencies = await self._aget_resolved_dependencies(
                    service_key=instantiation_key,
                    typevar_map=registration.typevar_map,
                )
                if resolved_dependencies.missing:
                    raise DIWireMissingDependenciesError(service_key, resolved_dependencies.missing)

                instance = instantiation_type(**resolved_dependencies.dependencies)

                if registration.lifetime == Lifetime.SINGLETON:
                    self._singletons[service_key] = instance
                elif registration.lifetime == Lifetime.SCOPED and cache_key is not None:
                    self._scoped_instances[cache_key] = instance

                return instance
            finally:
                if singleton_lock is not None and singleton_lock.locked():
                    singleton_lock.release()
                if scoped_lock is not None and scoped_lock.locked():
                    scoped_lock.release()
        finally:
            stack.pop()

    async def _aget_resolved_dependencies(
        self,
        service_key: ServiceKey,
        *,
        typevar_map: dict[Any, Any] | None = None,
    ) -> _ResolvedDependencies:
        """Asynchronously resolve dependencies for a service."""
        resolved_dependencies = _ResolvedDependencies()

        dependencies = self._dependencies_extractor.get_dependencies_with_defaults(
            service_key=service_key,
        )

        # Use pre-computed async deps cache when available (avoids registry lookups)
        async_deps = self._async_deps_cache.get(service_key)

        # Collect sync and async resolution tasks
        sync_deps: dict[str, Any] = {}
        async_tasks: list[tuple[str, Coroutine[Any, Any, Any]]] = []

        for name, param_info in dependencies.items():
            dep_key = param_info.service_key
            if self._handle_typevar_dependency(
                service_key=service_key,
                name=name,
                param_info=param_info,
                typevar_map=typevar_map,
                resolved_dependencies=resolved_dependencies,
            ):
                continue

            # Skip ignored types that aren't explicitly registered
            if dep_key.value in self._autoregister_ignores:
                # Check both global and scoped registries before marking as missing
                is_registered = dep_key in self._registry
                if not is_registered and self._has_scoped_registrations:
                    current_scope = _current_scope.get()
                    if current_scope is not None:
                        is_registered = (
                            self._get_scoped_registration(dep_key, current_scope) is not None
                        )
                if not is_registered:
                    if param_info.has_default:
                        continue
                    resolved_dependencies.missing.append(dep_key)
                    continue

            try:
                # Fast path: use cached async deps info when compiled
                if async_deps is not None and dep_key in async_deps:
                    async_tasks.append((name, self.aresolve(dep_key)))
                else:
                    # Try sync resolution first
                    # For uncompiled containers, fall back to registry check
                    if not self._is_compiled:
                        registration = self._registry.get(dep_key)
                        if registration is not None and registration.is_async:
                            async_tasks.append((name, self.aresolve(dep_key)))
                            continue

                    # Sync resolution (will raise DIWireAsyncDependencyInSyncContextError if truly async)
                    try:
                        sync_deps[name] = self.resolve(dep_key)
                    except DIWireAsyncDependencyInSyncContextError:
                        async_tasks.append((name, self.aresolve(dep_key)))
            except (DIWireCircularDependencyError, DIWireScopeMismatchError):
                raise
            except DIWireError:
                if not param_info.has_default:
                    resolved_dependencies.missing.append(dep_key)

        # Resolve async dependencies
        if async_tasks:
            if len(async_tasks) == 1:
                # Single async dependency - await directly (skip gather overhead)
                name, coro = async_tasks[0]
                resolved_dependencies.dependencies[name] = await coro
            else:
                # Multiple async dependencies - resolve in parallel
                # Wrap in create_task() so each coroutine gets its own context copy
                names, coros = zip(*async_tasks, strict=True)
                tasks = [asyncio.create_task(coro) for coro in coros]
                results = await asyncio.gather(*tasks)
                for name, result in zip(names, results, strict=True):
                    resolved_dependencies.dependencies[name] = result

        # Add sync dependencies
        resolved_dependencies.dependencies.update(sync_deps)

        return resolved_dependencies

    def _get_async_scope_exit_stack(
        self,
        scope_key: tuple[tuple[str | None, int], ...],
    ) -> AsyncExitStack:
        """Get or create an AsyncExitStack for the given scope."""
        async_exit_stack = self._async_scope_exit_stacks.get(scope_key)
        if async_exit_stack is None:
            async_exit_stack = AsyncExitStack()
            self._async_scope_exit_stacks[scope_key] = async_exit_stack
        return async_exit_stack

    async def _aclear_scope(self, scope_id: _ScopeId) -> None:
        """Asynchronously clear cached instances for a scope.

        This properly cleans up async generators registered in the scope.

        Args:
            scope_id: The scope ID to clear.

        """
        scope_key = scope_id.segments
        # Close sync exit stack
        scope_exit_stack = self._scope_exit_stacks.pop(scope_key, None)
        if scope_exit_stack is not None:
            scope_exit_stack.close()

        # Close async exit stack
        async_exit_stack = self._async_scope_exit_stacks.pop(scope_key, None)
        if async_exit_stack is not None:
            await async_exit_stack.aclose()

        # Remove all scoped instances with keys starting with this scope
        # Snapshot keys to avoid RuntimeError from dict mutation during iteration
        keys_to_remove = [k for k in list(self._scoped_instances) if k[0] == scope_key]
        for k in keys_to_remove:
            del self._scoped_instances[k]
        self._locks.clear_scope_locks(scope_key)

    def _register_active_scope(self, scope: ScopedContainer) -> None:
        """Register a scope as active for imperative close()."""
        with self._active_scopes_lock:
            if self._closed:
                raise DIWireContainerClosedError
            self._active_scopes.append(scope)

    def _unregister_active_scope(self, scope: ScopedContainer) -> None:
        """Unregister a scope when it is closed."""
        with self._active_scopes_lock, contextlib.suppress(ValueError):
            self._active_scopes.remove(scope)

    def _check_not_closed(self) -> None:
        """Raise an error if the container is closed."""
        if self._closed:
            raise DIWireContainerClosedError

    def close(self) -> None:
        """Close all active scopes and mark the container as closed.

        After calling this method, any attempt to resolve services or start
        new scopes will raise DIWireContainerClosedError.

        Scopes are closed in LIFO order (newest first).
        This method is idempotent - calling it multiple times is safe.

        If a scope's close() fails, that scope remains in _active_scopes
        and the exception is re-raised.
        """
        with self._active_scopes_lock:
            if self._closed:
                return
            self._closed = True
        while True:
            with self._active_scopes_lock:
                if not self._active_scopes:
                    break
                scope = self._active_scopes[-1]
            scope.close()
            with self._active_scopes_lock:
                if self._active_scopes and self._active_scopes[-1] is scope:
                    self._active_scopes.pop()

    async def aclose(self) -> None:
        """Asynchronously close all active scopes and mark the container as closed.

        Use this method when scopes contain async generator factories that
        need proper async cleanup.

        After calling this method, any attempt to resolve services or start
        new scopes will raise DIWireContainerClosedError.

        Scopes are closed in LIFO order (newest first).
        This method is idempotent - calling it multiple times is safe.

        This method will drain remaining scopes even if the container is
        already marked as closed. If a scope's aclose() fails, that scope
        remains in _active_scopes and the exception is re-raised.
        """
        with self._active_scopes_lock:
            self._closed = True
        while True:
            with self._active_scopes_lock:
                if not self._active_scopes:
                    break
                scope = self._active_scopes[-1]
            await scope.aclose()
            with self._active_scopes_lock:
                if self._active_scopes and self._active_scopes[-1] is scope:
                    self._active_scopes.pop()

    def close_scope(self, scope_name: str) -> None:
        """Close all active scopes that contain the given scope name.

        This closes the named scope and all its child scopes in LIFO order
        (children first, then parents).

        Args:
            scope_name: The name of the scope to close.

        Example:
            # Given hierarchy: app -> session -> request
            container.close_scope("session")  # Closes both "request" and "session"

        """
        while True:
            scope_to_close: ScopedContainer | None = None
            with self._active_scopes_lock:
                # Find scopes containing the scope_name, process from end (LIFO)
                for i in range(len(self._active_scopes) - 1, -1, -1):
                    scope = self._active_scopes[i]
                    if scope._scope_id.contains_scope(scope_name):  # noqa: SLF001
                        scope_to_close = scope
                        break
            if scope_to_close is None:
                return
            scope_to_close.close()

    async def aclose_scope(self, scope_name: str) -> None:
        """Asynchronously close all active scopes that contain the given scope name.

        This closes the named scope and all its child scopes in LIFO order
        (children first, then parents).

        Args:
            scope_name: The name of the scope to close.

        """
        while True:
            scope_to_close: ScopedContainer | None = None
            with self._active_scopes_lock:
                for i in range(len(self._active_scopes) - 1, -1, -1):
                    scope = self._active_scopes[i]
                    if scope._scope_id.contains_scope(scope_name):  # noqa: SLF001
                        scope_to_close = scope
                        break
            if scope_to_close is None:
                return
            await scope_to_close.aclose()

    def _get_scoped_registration(
        self,
        service_key: ServiceKey,
        current_scope: _ScopeId,
    ) -> Registration | None:
        """Get a scoped registration for a service, if one exists.

        Only checks the scoped registry, does not fall back to global registry.
        Uses tuple iteration instead of string split/join for performance.
        """
        # Check from most specific to least specific
        # Only check named scopes (skip anonymous segments where name is None)
        for i in range(len(current_scope.segments), 0, -1):
            name, _ = current_scope.segments[i - 1]
            if name is not None:
                scoped_reg = self._scoped_registry.get((service_key, name))
                if scoped_reg is not None:
                    return scoped_reg
        return None

    def _get_scoped_open_generic_registration(
        self,
        origin: type,
        component: Component | None,
        current_scope: _ScopeId,
    ) -> _OpenGenericRegistration | None:
        """Get a scoped open generic registration for a matching scope, if any."""
        for i in range(len(current_scope.segments), 0, -1):
            name, _ = current_scope.segments[i - 1]
            if name is not None:
                scoped_reg = self._scoped_open_generic_registry.get((origin, component, name))
                if scoped_reg is not None:
                    return scoped_reg
        return None

    def _validate_typevar_map(
        self,
        service_key: ServiceKey,
        typevar_map: dict[Any, Any],
    ) -> None:
        """Validate TypeVar bounds and constraints for a closed generic."""
        for typevar, arg in typevar_map.items():
            constraints = getattr(typevar, "__constraints__", ())
            bound = getattr(typevar, "__bound__", None)
            if constraints:
                if not any(
                    _type_arg_matches_constraint(arg, constraint) for constraint in constraints
                ):
                    raise DIWireInvalidGenericTypeArgumentError(
                        service_key,
                        typevar,
                        arg,
                        f"Expected one of {constraints!r}.",
                    )
                continue
            if (
                bound is not None
                and not _is_any_type(bound)
                and not _type_arg_matches_constraint(arg, bound)
            ):
                raise DIWireInvalidGenericTypeArgumentError(
                    service_key,
                    typevar,
                    arg,
                    f"Expected bound {bound!r}.",
                )

    def _get_typevar_argument(
        self,
        typevar: Any,
        typevar_map: dict[Any, Any],
    ) -> Any | None:
        """Lookup the concrete argument for a TypeVar from a map."""
        if typevar in typevar_map:
            return typevar_map[typevar]
        return None

    def _handle_typevar_dependency(
        self,
        *,
        service_key: ServiceKey,
        name: str,
        param_info: ParameterInfo,
        typevar_map: dict[Any, Any] | None,
        resolved_dependencies: _ResolvedDependencies,
    ) -> bool:
        """Inject TypeVar-bound arguments if present; return True when handled."""
        if param_info.typevar is None:
            return False
        if typevar_map is not None:
            type_arg = self._get_typevar_argument(param_info.typevar, typevar_map)
            if type_arg is not None:
                resolved_dependencies.dependencies[name] = type_arg
                return True
        if param_info.has_default:
            return True
        raise DIWireOpenGenericResolutionError(
            service_key,
            f"Type argument for {getattr(param_info.typevar, '__name__', param_info.typevar)!r} "
            "is missing.",
        )

    def _resolve_open_generic_registration(
        self,
        service_key: ServiceKey,
        current_scope: _ScopeId | None,
    ) -> Registration | None:
        origin, args = _get_generic_origin_and_args(service_key.value)
        if origin is None or not args:
            return None
        if any(_is_typevar(arg) for arg in args):
            raise DIWireOpenGenericResolutionError(
                service_key,
                "Type arguments must be concrete.",
            )

        open_registration: _OpenGenericRegistration | None = None
        if current_scope is not None:
            open_registration = self._get_scoped_open_generic_registration(
                origin,
                service_key.component,
                current_scope,
            )
        if open_registration is None:
            open_registration = self._open_generic_registry.get((origin, service_key.component))
        if open_registration is None:
            return None

        if len(args) != len(open_registration.typevars):
            raise DIWireOpenGenericResolutionError(
                service_key,
                f"Expected {len(open_registration.typevars)} type argument(s), got {len(args)}.",
            )

        typevar_map = dict(zip(open_registration.typevars, args, strict=True))
        self._validate_typevar_map(service_key, typevar_map)

        base = open_registration.registration
        registration = Registration(
            service_key=service_key,
            factory=base.factory,
            instance=base.instance,
            lifetime=base.lifetime,
            scope=base.scope,
            is_async=base.is_async,
            concrete_type=base.concrete_type,
            typevar_map=typevar_map,
        )
        if base.scope is not None:
            self._scoped_registry[(service_key, base.scope)] = registration
            self._has_scoped_registrations = True
        else:
            self._registry[service_key] = registration

        return registration

    def _get_registration(
        self,
        service_key: ServiceKey,
        current_scope: _ScopeId | None,
    ) -> Registration:
        """Get the registration for a service, checking scoped registry first.

        Looks for a matching scoped registration based on the current scope hierarchy,
        then falls back to the global registry, then auto-registration.
        """
        # Check scoped registry - find the most specific matching scope
        if current_scope is not None:
            scoped_reg = self._get_scoped_registration(service_key, current_scope)
            if scoped_reg is not None:
                return scoped_reg

        # Fall back to global registry
        registration = self._registry.get(service_key)
        if registration is not None:
            return registration

        registration = self._resolve_open_generic_registration(service_key, current_scope)
        if registration is not None:
            return registration

        # Auto-register if enabled
        if not self._autoregister:
            raise DIWireServiceNotRegisteredError(service_key)

        # Check if there's any scoped registration for this key before auto-registering
        if self._has_scoped_registrations:
            scoped_reg = self._find_any_scoped_registration(service_key)
            if scoped_reg is not None:
                raise DIWireScopeMismatchError(
                    service_key,
                    scoped_reg.scope,  # type: ignore[arg-type]
                    current_scope.path if current_scope else None,
                )

        registration = self._get_auto_registration(service_key=service_key)
        self._registry[service_key] = registration
        return registration

    def _find_any_scoped_registration(self, service_key: ServiceKey) -> Registration | None:
        """Find any scoped registration for the given service key, regardless of scope."""
        for (sk, _scope_name), reg in self._scoped_registry.items():
            if sk == service_key:
                return reg
        return None

    def _get_cache_scope(
        self,
        current_scope: _ScopeId | None,
        registered_scope: str | None,
    ) -> tuple[tuple[str | None, int], ...] | None:
        """Get the scope key to use for caching scoped instances.

        Returns the tuple key up to and including the registered scope segment.
        E.g., current=_ScopeId((("request", 1), ("child", 2))), registered="request"
        -> (("request", 1),)
        """
        if current_scope is None:
            return None
        if registered_scope is None:
            return current_scope.segments

        # Find segments up to and including the registered scope name
        return current_scope.get_cache_key_for_scope(registered_scope)

    def _scope_matches(self, current_scope: _ScopeId, registered_scope: str) -> bool:
        """Check if the current scope matches or contains the registered scope.

        Uses tuple iteration instead of string operations for performance.
        """
        return current_scope.contains_scope(registered_scope)

    def _find_scope_in_dependencies(
        self,
        deps: dict[str, ServiceKey],
        visited: set[ServiceKey] | None = None,
    ) -> str | None:
        """Find a scope from registered dependencies (recursively)."""
        if visited is None:
            visited = set()

        for dep_key in deps.values():
            if dep_key in visited:
                continue
            visited.add(dep_key)

            # Collect all scopes from both registries
            found_scopes: set[str] = set()

            # Check global registry
            registration = self._registry.get(dep_key)
            if registration is not None and registration.scope is not None:
                found_scopes.add(registration.scope)

            # Check scoped registry for all entries matching this dep_key
            for (service_key, _scope_name), scoped_reg in self._scoped_registry.items():
                if service_key == dep_key and scoped_reg.scope is not None:
                    found_scopes.add(scoped_reg.scope)

            # If we found exactly one unique scope, return it
            if len(found_scopes) == 1:
                return next(iter(found_scopes))
            # If multiple different scopes (ambiguous), skip and check nested deps
            # If no scopes found, also check nested deps

            # Check nested dependencies (skip if extraction fails for non-class types)
            try:
                nested_deps = self._dependencies_extractor.get_dependencies(dep_key)
                nested_scope = self._find_scope_in_dependencies(nested_deps, visited)
                if nested_scope is not None:
                    return nested_scope
            except DIWireError:
                continue

        return None

    def _get_auto_registration(self, service_key: ServiceKey) -> Registration:
        if service_key.component is not None:
            raise DIWireComponentSpecifiedError(service_key)

        if service_key.value in self._autoregister_ignores:
            raise DIWireIgnoredServiceError(service_key)

        if _is_union_type(service_key.value):
            raise DIWireUnionTypeError(service_key)

        if not isinstance(service_key.value, type):
            raise DIWireNotAClassError(service_key)

        for base_cls, registration_factory in self._autoregister_registration_factories.items():
            if issubclass(service_key.value, base_cls):
                return registration_factory(service_key.value)

        return Registration(
            service_key=service_key,
            lifetime=self._autoregister_default_lifetime,
        )

    def _get_resolved_dependencies(
        self,
        service_key: ServiceKey,
        *,
        typevar_map: dict[Any, Any] | None = None,
    ) -> _ResolvedDependencies:
        resolved_dependencies = _ResolvedDependencies()

        dependencies = self._dependencies_extractor.get_dependencies_with_defaults(
            service_key=service_key,
        )
        for name, param_info in dependencies.items():
            if self._handle_typevar_dependency(
                service_key=service_key,
                name=name,
                param_info=param_info,
                typevar_map=typevar_map,
                resolved_dependencies=resolved_dependencies,
            ):
                continue
            # Skip ignored types that aren't explicitly registered
            if param_info.service_key.value in self._autoregister_ignores:
                # Check both global and scoped registries before marking as missing
                is_registered = param_info.service_key in self._registry
                if not is_registered and self._has_scoped_registrations:
                    current_scope = _current_scope.get()
                    if current_scope is not None:
                        is_registered = (
                            self._get_scoped_registration(param_info.service_key, current_scope)
                            is not None
                        )
                if not is_registered:
                    if param_info.has_default:
                        continue
                    resolved_dependencies.missing.append(param_info.service_key)
                    continue

            try:
                resolved_dependencies.dependencies[name] = self.resolve(param_info.service_key)
            except (
                DIWireCircularDependencyError,
                DIWireScopeMismatchError,
                DIWireAsyncDependencyInSyncContextError,
            ):
                raise
            except DIWireError:
                if not param_info.has_default:
                    resolved_dependencies.missing.append(param_info.service_key)

        return resolved_dependencies
