from __future__ import annotations

import asyncio
import inspect
import itertools
import threading
import types
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
from contextlib import AsyncExitStack, ExitStack
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from inspect import signature
from types import FunctionType, MethodType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Generic,
    TypeVar,
    get_args,
    get_origin,
    overload,
)

if TYPE_CHECKING:
    from typing_extensions import Self

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
from diwire.defaults import (
    DEFAULT_AUTOREGISTER_IGNORES,
    DEFAULT_AUTOREGISTER_LIFETIME,
    DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES,
)
from diwire.dependencies import DependenciesExtractor
from diwire.exceptions import (
    DIWireAsyncCleanupWithoutEventLoopError,
    DIWireAsyncDependencyInSyncContextError,
    DIWireAsyncGeneratorFactoryDidNotYieldError,
    DIWireAsyncGeneratorFactoryWithoutScopeError,
    DIWireCircularDependencyError,
    DIWireComponentSpecifiedError,
    DIWireError,
    DIWireGeneratorFactoryDidNotYieldError,
    DIWireGeneratorFactoryUnsupportedLifetimeError,
    DIWireGeneratorFactoryWithoutScopeError,
    DIWireIgnoredServiceError,
    DIWireMissingDependenciesError,
    DIWireNotAClassError,
    DIWireProvidesRequiresClassError,
    DIWireScopedSingletonWithoutScopeError,
    DIWireScopeMismatchError,
    DIWireServiceNotRegisteredError,
)
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Factory, FromDI, Lifetime

T = TypeVar("T", bound=Any)


@dataclass(frozen=True, slots=True)
class ScopeId:
    """Tuple-based scope identifier for fast scope matching.

    Replaces string-based scope paths to eliminate split/join operations.
    Each segment is a (scope_name, instance_id) pair.
    """

    segments: tuple[tuple[str | None, int], ...]

    @property
    def path(self) -> str:
        """Generate string path only when needed (error messages)."""
        parts = []
        for name, id_ in self.segments:
            parts.append(f"{name}/{id_}" if name else str(id_))
        return "/".join(parts)

    def contains_scope(self, scope_name: str) -> bool:
        """Check if this scope contains the given scope name."""
        return any(name == scope_name for name, _ in self.segments)

    def get_cache_key_for_scope(self, scope_name: str) -> tuple[tuple[str | None, int], ...] | None:
        """Get the tuple key up to and including the specified scope segment.

        Returns None if the scope is not found.
        """
        for i, (name, _) in enumerate(self.segments):
            if name == scope_name:
                return self.segments[: i + 1]
        return None


# Context variable for resolution tracking (works with both threads and async tasks)
# Stores (task_id, stack) tuple to detect when stack needs cloning for new async tasks
_resolution_stack: ContextVar[tuple[int | None, list[ServiceKey]] | None] = ContextVar(
    "resolution_stack",
    default=None,
)

# Context variable for current scope
_current_scope: ContextVar[ScopeId | None] = ContextVar("current_scope", default=None)


def _get_context_id() -> int | None:
    """Get an identifier for the current execution context.

    Returns the id of the current async task if running in an async context,
    or None if running in a sync context.
    """
    try:
        task = asyncio.current_task()
        return id(task) if task is not None else None
    except RuntimeError:
        return None


def _get_resolution_stack() -> list[ServiceKey]:
    """Get the current context's resolution stack.

    When called from a different async task than the one that created the stack,
    returns a cloned copy to ensure task isolation during parallel resolution.
    """
    current_task_id = _get_context_id()
    stored = _resolution_stack.get()

    if stored is None:
        # Create a new list for this context
        stack: list[ServiceKey] = []
        _resolution_stack.set((current_task_id, stack))
        return stack

    owner_task_id, stack = stored

    # If we're in a different async task, clone the stack for isolation
    if current_task_id is not None and owner_task_id != current_task_id:
        cloned_stack = list(stack)
        _resolution_stack.set((current_task_id, cloned_stack))
        return cloned_stack

    return stack


def _is_async_factory(factory: Any) -> bool:
    """Check if a factory is async (coroutine function or async generator function)."""
    # Handle callable classes by checking __call__ method
    if isinstance(factory, type):
        call_method = getattr(factory, "__call__", None)  # noqa: B004
        if call_method is not None:
            return inspect.iscoroutinefunction(call_method) or inspect.isasyncgenfunction(
                call_method,
            )
        return False  # pragma: no cover - __call__ is never None for a normal class

    # Handle callable instances (objects with __call__ that aren't functions/classes)
    if callable(factory) and not inspect.isfunction(factory) and not inspect.ismethod(factory):
        wrapped_factory = getattr(factory, "func", None)
        if wrapped_factory is not None and (
            inspect.isfunction(wrapped_factory) or inspect.ismethod(wrapped_factory)
        ):
            return inspect.iscoroutinefunction(wrapped_factory) or inspect.isasyncgenfunction(
                wrapped_factory,
            )
        call_method = getattr(factory, "__call__", None)  # noqa: B004
        # Callable objects always have __call__, so this is always True
        if call_method is not None:  # pragma: no branch
            return inspect.iscoroutinefunction(call_method) or inspect.isasyncgenfunction(
                call_method,
            )

    return inspect.iscoroutinefunction(factory) or inspect.isasyncgenfunction(factory)


@dataclass(kw_only=True, slots=True, frozen=True)
class ResolvedDependencies:
    """Result of dependency resolution containing resolved values and any missing keys."""

    dependencies: dict[str, Any] = field(default_factory=dict)
    missing: list[ServiceKey] = field(default_factory=list)


def _has_fromdi_annotation(param: inspect.Parameter) -> bool:
    """Check if a parameter has FromDI in its annotation.

    Handles both:
    - String annotations (from `from __future__ import annotations` / PEP 563)
    - Resolved Annotated types with FromDI metadata
    """
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False

    # String annotation check (PEP 563)
    if isinstance(annotation, str):
        return "FromDI" in annotation

    # Check for Annotated type with FromDI metadata
    # For Annotated[T, ...], args[0] is T and args[1:] are the metadata
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return any(isinstance(arg, FromDI) for arg in args[1:])

    return False


def _build_signature_without_fromdi(func: Callable[..., Any]) -> inspect.Signature:
    """Build a signature excluding parameters marked with FromDI."""
    original_sig = signature(func)
    new_params = [p for p in original_sig.parameters.values() if not _has_fromdi_annotation(p)]
    return original_sig.replace(parameters=new_params)


class Injected(Generic[T]):
    """A callable wrapper that resolves dependencies on each call.

    This ensures transient dependencies are created fresh on every invocation,
    while singletons are still shared as expected.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., T],
        container: Container,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., T] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_fromdi(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped function, resolving FromDI dependencies fresh each time."""
        self._ensure_initialized()
        resolved = self._resolve_injected_dependencies()
        # Merge resolved dependencies with explicit kwargs (explicit kwargs take precedence)
        merged_kwargs = {**resolved, **kwargs}
        return self._func(*args, **merged_kwargs)

    def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Resolve dependencies marked with FromDI."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        return {name: self._container.resolve(dep) for name, dep in injected_deps.items()}

    def __repr__(self) -> str:
        return f"Injected({self._func!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


@dataclass
class ScopedContainer:
    """A context manager for scoped dependency resolution.

    Supports both sync and async context managers:
    - `with container.start_scope()` for sync usage
    - `async with container.start_scope()` for async usage with proper async cleanup
    """

    _container: Container
    _scope_id: ScopeId
    _token: Any = field(default=None, init=False)
    _exited: bool = field(default=False, init=False)

    def resolve(self, key: Any) -> Any:
        """Resolve a service within this scope."""
        if self._exited:
            current = _current_scope.get()
            raise DIWireScopeMismatchError(
                ServiceKey.from_value(key),
                self._scope_id.path,
                current.path if current else None,
            )
        return self._container.resolve(key)

    async def aresolve(self, key: Any) -> Any:
        """Asynchronously resolve a service within this scope."""
        if self._exited:
            current = _current_scope.get()
            raise DIWireScopeMismatchError(
                ServiceKey.from_value(key),
                self._scope_id.path,
                current.path if current else None,
            )
        return await self._container.aresolve(key)

    def start_scope(self, scope_name: str | None = None) -> ScopedContainer:
        """Start a nested scope."""
        return self._container.start_scope(scope_name)

    def __enter__(self) -> Self:
        self._token = _current_scope.set(self._scope_id)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        _current_scope.reset(self._token)
        self._container.clear_scope(self._scope_id)
        self._exited = True

    async def __aenter__(self) -> Self:
        self._token = _current_scope.set(self._scope_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        _current_scope.reset(self._token)
        await self._container.aclear_scope(self._scope_id)
        self._exited = True


class ScopedInjected(Generic[T]):
    """A callable wrapper that creates a new scope for each call.

    Similar to Injected, but ensures SCOPED_SINGLETON dependencies are shared
    within a single call invocation.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., T],
        container: Container,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
        scope_name: str,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None
        self._scope_name = scope_name

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., T] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_fromdi(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped function, creating a new scope for this invocation."""
        self._ensure_initialized()
        with self._container.start_scope(self._scope_name):
            resolved = self._resolve_injected_dependencies()
            return self._func(*args, **{**resolved, **kwargs})

    def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Resolve dependencies marked with FromDI."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        return {name: self._container.resolve(dep) for name, dep in injected_deps.items()}

    def __repr__(self) -> str:
        return f"ScopedInjected({self._func!r}, scope={self._scope_name!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


class AsyncInjected(Generic[T]):
    """A callable wrapper that resolves dependencies on each call for async functions.

    This ensures transient dependencies are created fresh on every invocation,
    while singletons are still shared as expected.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        container: Container,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, T]] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_fromdi(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    async def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped async function, resolving FromDI dependencies fresh each time."""
        self._ensure_initialized()
        resolved = await self._resolve_injected_dependencies()
        # Merge resolved dependencies with explicit kwargs (explicit kwargs take precedence)
        merged_kwargs = {**resolved, **kwargs}
        return await self._func(*args, **merged_kwargs)

    async def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Asynchronously resolve dependencies marked with FromDI."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        # Resolve all dependencies in parallel
        # Wrap in create_task() so each coroutine gets its own context copy
        coros = {name: self._container.aresolve(dep) for name, dep in injected_deps.items()}
        tasks = [asyncio.create_task(coro) for coro in coros.values()]
        results = await asyncio.gather(*tasks)
        return dict(zip(coros.keys(), results, strict=True))

    def __repr__(self) -> str:
        return f"AsyncInjected({self._func!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


class AsyncScopedInjected(Generic[T]):
    """A callable wrapper that creates a new async scope for each call.

    Similar to AsyncInjected, but ensures SCOPED_SINGLETON dependencies are shared
    within a single call invocation.

    Uses lazy initialization to support `from __future__ import annotations`,
    deferring type hint resolution until the first call.
    """

    def __init__(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        container: Container,
        dependencies_extractor: DependenciesExtractor,
        service_key: ServiceKey,
        scope_name: str,
    ) -> None:
        self._func = func
        self._container = container
        self._dependencies_extractor = dependencies_extractor
        self._service_key = service_key
        self._injected_params: set[str] | None = None
        self._scope_name = scope_name

        # Preserve function metadata for introspection
        wraps(func)(self)
        self.__name__: str = getattr(func, "__name__", repr(func))
        self.__wrapped__: Callable[..., Coroutine[Any, Any, T]] = func

        # Build signature at decoration time by detecting FromDI in annotations
        # This works even with string annotations from PEP 563
        self.__signature__ = _build_signature_without_fromdi(func)

    def _ensure_initialized(self) -> None:
        """Lazily extract dependencies on first call."""
        if self._injected_params is not None:
            return
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        self._injected_params = set(injected_deps.keys())

    async def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Call the wrapped async function, creating a new scope for this invocation."""
        self._ensure_initialized()
        async with self._container.start_scope(self._scope_name):
            resolved = await self._resolve_injected_dependencies()
            return await self._func(*args, **{**resolved, **kwargs})

    async def _resolve_injected_dependencies(self) -> dict[str, Any]:
        """Asynchronously resolve dependencies marked with FromDI."""
        injected_deps = self._dependencies_extractor.get_injected_dependencies(
            service_key=self._service_key,
        )
        # Resolve all dependencies in parallel
        # Wrap in create_task() so each coroutine gets its own context copy
        coros = {name: self._container.aresolve(dep) for name, dep in injected_deps.items()}
        tasks = [asyncio.create_task(coro) for coro in coros.values()]
        results = await asyncio.gather(*tasks)
        return dict(zip(coros.keys(), results, strict=True))

    def __repr__(self) -> str:
        return f"AsyncScopedInjected({self._func!r}, scope={self._scope_name!r})"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        """Descriptor protocol to bind this callable to an instance when used as a method."""
        if obj is None:
            return self
        return types.MethodType(self, obj)


class Container:
    """Dependency injection container for registering and resolving services.

    Supports automatic registration, lifetime singleton/transient, and factory patterns.
    """

    # Class-level counter for generating unique scope IDs (faster than UUID)
    _scope_counter: ClassVar[itertools.count[int]] = itertools.count()

    __slots__ = (
        "_async_deps_cache",
        "_async_scope_exit_stacks",
        "_auto_compile",
        "_autoregister_default_lifetime",
        "_autoregister_ignores",
        "_autoregister_registration_factories",
        "_cleanup_tasks",
        "_compiled_providers",
        "_dependencies_extractor",
        "_has_scoped_registrations",
        "_is_compiled",
        "_register_if_missing",
        "_registry",
        "_scope_exit_stacks",
        "_scoped_compiled_providers",
        "_scoped_instances",
        "_scoped_registry",
        "_scoped_singleton_locks",
        "_scoped_singleton_locks_lock",
        "_singleton_locks",
        "_singleton_locks_lock",
        "_singletons",
        "_sync_scoped_singleton_locks",
        "_sync_scoped_singleton_locks_lock",
        "_sync_singleton_locks",
        "_sync_singleton_locks_lock",
        "_type_providers",
        "_type_singletons",
    )

    def __init__(
        self,
        *,
        register_if_missing: bool = True,
        autoregister_ignores: set[type[Any]] | None = None,
        autoregister_registration_factories: dict[type[Any], Callable[[Any], Registration]]
        | None = None,
        autoregister_default_lifetime: Lifetime = DEFAULT_AUTOREGISTER_LIFETIME,
        auto_compile: bool = True,
    ) -> None:
        self._register_if_missing = register_if_missing
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

        # Per-cache-key locks for async scoped singleton resolution to prevent races
        self._scoped_singleton_locks: dict[
            tuple[tuple[tuple[str | None, int], ...], ServiceKey],
            asyncio.Lock,
        ] = {}
        self._scoped_singleton_locks_lock = asyncio.Lock()

        # Per-cache-key locks for sync scoped singleton resolution to prevent races
        self._sync_scoped_singleton_locks: dict[
            tuple[tuple[tuple[str | None, int], ...], ServiceKey],
            threading.Lock,
        ] = {}
        self._sync_scoped_singleton_locks_lock = threading.Lock()

        # Per-service-key locks for async singleton resolution to prevent race conditions
        self._singleton_locks: dict[ServiceKey, asyncio.Lock] = {}
        self._singleton_locks_lock = asyncio.Lock()

        # Per-service-key locks for sync singleton resolution to prevent race conditions
        self._sync_singleton_locks: dict[ServiceKey, threading.Lock] = {}
        self._sync_singleton_locks_lock = threading.Lock()

        self.register(type(self), instance=self, lifetime=Lifetime.SINGLETON)

    def register(
        self,
        key: Any,
        /,
        factory: Factory | None = None,
        instance: Any | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        scope: str | None = None,
        is_async: bool | None = None,
        provides: Any | None = None,
    ) -> None:
        """Register a service with the container.

        Args:
            key: The service key to register. When used with `provides`, this is the
                concrete implementation class.
            factory: Optional factory to create instances.
            instance: Optional pre-created instance.
            lifetime: The lifetime of the service. This default applies only to explicit
                registrations via `register`; auto-registration uses
                `autoregister_default_lifetime` from container configuration.
            scope: Optional scope name for SCOPED_SINGLETON services.
            is_async: Whether the factory is async. If None, auto-detected from factory.
            provides: Optional interface/abstract type that this registration provides.
                When specified, the service is registered under this type instead of `key`.

        Raises:
            DIWireScopedSingletonWithoutScopeError: If lifetime is SCOPED_SINGLETON but no scope is provided.
            DIWireProvidesRequiresClassError: If `provides` is used but `key` is not a class
                (when no factory/instance is given).

        """
        # Determine service_key and concrete_type based on provides parameter
        if provides is not None:
            service_key = ServiceKey.from_value(provides)
            if instance is None and factory is None:
                if not isinstance(key, type):
                    raise DIWireProvidesRequiresClassError(key, provides)
                concrete_type: type | None = key
            else:
                concrete_type = key if isinstance(key, type) else None
        else:
            service_key = ServiceKey.from_value(key)
            concrete_type = None

        if lifetime == Lifetime.SCOPED_SINGLETON and scope is None:
            raise DIWireScopedSingletonWithoutScopeError(service_key)

        # Auto-detect if factory is async when not explicitly specified
        detected_is_async = False
        if is_async is not None:
            detected_is_async = is_async
        elif factory is not None:
            detected_is_async = _is_async_factory(factory)

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
        if lifetime == Lifetime.SCOPED_SINGLETON:
            self._has_scoped_registrations = True

        # Invalidate compiled state when registrations change
        self._is_compiled = False

    def start_scope(self, scope_name: str | None = None) -> ScopedContainer:
        """Start a new scope for resolving SCOPED_SINGLETON dependencies.

        Args:
            scope_name: Optional name for the scope. If not provided, an integer ID is generated.

        Returns:
            A ScopedContainer context manager.

        Note:
            Nested scopes inherit from parent scopes. A scope started within
            another scope will have access to dependencies registered for the
            parent scope.

        """
        # Generate unique instance ID for each scope (integer is faster than UUID)
        instance_id = next(self._scope_counter)

        # Create new segment as tuple
        new_segment = (scope_name, instance_id)

        # Build scope by appending to current scope's segments
        current = _current_scope.get()
        segments = (*current.segments, new_segment) if current is not None else (new_segment,)

        scope_id = ScopeId(segments=segments)
        return ScopedContainer(_container=self, _scope_id=scope_id)

    def clear_scope(self, scope_id: ScopeId) -> None:
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
                # No running event loop - leave stack in place for later aclear_scope() call
                scope_name = scope_key[-1][0] if scope_key else None
                raise DIWireAsyncCleanupWithoutEventLoopError(scope_name) from None
            # Event loop is running - schedule cleanup as a task
            task = loop.create_task(async_exit_stack.aclose())
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)
            # Only remove after successfully scheduling cleanup
            del self._async_scope_exit_stacks[scope_key]

        # Remove all scoped instances with keys starting with this scope
        keys_to_remove = [k for k in self._scoped_instances if k[0] == scope_key]
        for k in keys_to_remove:
            del self._scoped_instances[k]
        scoped_lock_keys = [k for k in self._sync_scoped_singleton_locks if k[0] == scope_key]
        for k in scoped_lock_keys:
            del self._sync_scoped_singleton_locks[k]
        async_scoped_lock_keys = [k for k in self._scoped_singleton_locks if k[0] == scope_key]
        for k in async_scoped_lock_keys:
            del self._scoped_singleton_locks[k]

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
        for service_key, provider in self._compiled_providers.items():
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
        for service_key in self._registry:
            if not isinstance(service_key.value, type):
                continue

            async_deps: set[ServiceKey] = set()
            try:
                deps = self._dependencies_extractor.get_dependencies_with_defaults(service_key)
                for param_info in deps.values():
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
                # They may have FromDI parameters that need injection
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
        if self._register_if_missing:
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
    ) -> AsyncInjected[T]: ...

    @overload
    def resolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: str,
    ) -> AsyncScopedInjected[T]: ...

    @overload
    def resolve(self, key: Callable[..., T], *, scope: None = None) -> Injected[T]: ...

    @overload
    def resolve(self, key: Callable[..., T], *, scope: str) -> ScopedInjected[T]: ...

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
            async def handler(service: Annotated[Service, FromDI()]) -> dict:
                ...

        """
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
                    return AsyncScopedInjected(
                        func=service_key.value,
                        container=self,
                        dependencies_extractor=self._dependencies_extractor,
                        service_key=service_key,
                        scope_name=effective_scope,
                    )
                return ScopedInjected(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                    scope_name=effective_scope,
                )
            if is_async_func:
                return AsyncInjected(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                )
            return Injected(
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
                    scoped_lock = self._get_sync_scoped_singleton_lock(cache_key)
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
                registration.lifetime == Lifetime.SCOPED_SINGLETON
                and cache_key is not None  # type: ignore[redundant-expr]
                and registration.instance is None
            ):
                scoped_lock = self._get_sync_scoped_singleton_lock(cache_key)
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
                singleton_lock = self._get_sync_singleton_lock(service_key)
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
                        resolved = self._get_resolved_dependencies(factory_key)
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
                    elif (
                        registration.lifetime == Lifetime.SCOPED_SINGLETON and cache_key is not None
                    ):
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
                )
                if resolved_dependencies.missing:
                    raise DIWireMissingDependenciesError(service_key, resolved_dependencies.missing)

                instance = instantiation_type(**resolved_dependencies.dependencies)

                if registration.lifetime == Lifetime.SINGLETON:
                    self._singletons[service_key] = instance
                elif registration.lifetime == Lifetime.SCOPED_SINGLETON and cache_key is not None:
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
    ) -> AsyncInjected[T]: ...

    @overload
    async def aresolve(
        self,
        key: Callable[..., Coroutine[Any, Any, T]],
        *,
        scope: str,
    ) -> AsyncScopedInjected[T]: ...

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
                    return AsyncScopedInjected(
                        func=service_key.value,
                        container=self,
                        dependencies_extractor=self._dependencies_extractor,
                        service_key=service_key,
                        scope_name=effective_scope,
                    )
                return ScopedInjected(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                    scope_name=effective_scope,
                )
            if is_async_func:
                return AsyncInjected(
                    func=service_key.value,
                    container=self,
                    dependencies_extractor=self._dependencies_extractor,
                    service_key=service_key,
                )
            return Injected(
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
                registration.lifetime == Lifetime.SCOPED_SINGLETON
                and cache_key is not None
                and registration.instance is None
            ):
                scoped_lock = await self._get_scoped_singleton_lock(cache_key)
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
                singleton_lock = await self._get_singleton_lock(service_key)
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
                        resolved = await self._aget_resolved_dependencies(factory_key)
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
                    elif (
                        registration.lifetime == Lifetime.SCOPED_SINGLETON and cache_key is not None
                    ):
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
                )
                if resolved_dependencies.missing:
                    raise DIWireMissingDependenciesError(service_key, resolved_dependencies.missing)

                instance = instantiation_type(**resolved_dependencies.dependencies)

                if registration.lifetime == Lifetime.SINGLETON:
                    self._singletons[service_key] = instance
                elif registration.lifetime == Lifetime.SCOPED_SINGLETON and cache_key is not None:
                    self._scoped_instances[cache_key] = instance

                return instance
            finally:
                if singleton_lock is not None and singleton_lock.locked():
                    singleton_lock.release()
                if scoped_lock is not None and scoped_lock.locked():
                    scoped_lock.release()
        finally:
            stack.pop()

    async def _aget_resolved_dependencies(self, service_key: ServiceKey) -> ResolvedDependencies:
        """Asynchronously resolve dependencies for a service."""
        resolved_dependencies = ResolvedDependencies()

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

    async def _get_scoped_singleton_lock(
        self,
        cache_key: tuple[tuple[tuple[str | None, int], ...], ServiceKey],
    ) -> asyncio.Lock:
        """Get or create an async lock for scoped singleton resolution of the cache key.

        Uses double-checked locking to minimize lock contention.
        """
        if cache_key not in self._scoped_singleton_locks:
            async with self._scoped_singleton_locks_lock:
                # Second check after acquiring lock - race timing dependent
                if (
                    cache_key not in self._scoped_singleton_locks
                ):  # pragma: no cover - race timing dependent
                    self._scoped_singleton_locks[cache_key] = asyncio.Lock()
        return self._scoped_singleton_locks[cache_key]

    def _get_sync_scoped_singleton_lock(
        self,
        cache_key: tuple[tuple[tuple[str | None, int], ...], ServiceKey],
    ) -> threading.Lock:
        """Get or create a thread lock for scoped singleton resolution of the cache key.

        Uses double-checked locking to minimize lock contention.
        """
        if cache_key not in self._sync_scoped_singleton_locks:
            with self._sync_scoped_singleton_locks_lock:
                # Second check after acquiring lock - race timing dependent
                if (
                    cache_key not in self._sync_scoped_singleton_locks
                ):  # pragma: no cover - race timing dependent
                    self._sync_scoped_singleton_locks[cache_key] = threading.Lock()
        return self._sync_scoped_singleton_locks[cache_key]

    async def _get_singleton_lock(self, key: ServiceKey) -> asyncio.Lock:
        """Get or create an async lock for singleton resolution of the given service key.

        Uses double-checked locking to minimize lock contention.
        """
        if key not in self._singleton_locks:
            async with self._singleton_locks_lock:
                # Second check after acquiring lock - race timing dependent
                if key not in self._singleton_locks:  # pragma: no cover - race timing dependent
                    self._singleton_locks[key] = asyncio.Lock()
        return self._singleton_locks[key]

    def _get_sync_singleton_lock(self, key: ServiceKey) -> threading.Lock:
        """Get or create a thread lock for singleton resolution of the given service key.

        Uses double-checked locking to minimize lock contention.
        """
        if key not in self._sync_singleton_locks:
            with self._sync_singleton_locks_lock:
                # Second check after acquiring lock - race timing dependent
                if (
                    key not in self._sync_singleton_locks
                ):  # pragma: no cover - race timing dependent
                    self._sync_singleton_locks[key] = threading.Lock()
        return self._sync_singleton_locks[key]

    async def aclear_scope(self, scope_id: ScopeId) -> None:
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
        keys_to_remove = [k for k in self._scoped_instances if k[0] == scope_key]
        for k in keys_to_remove:
            del self._scoped_instances[k]
        scoped_lock_keys = [k for k in self._sync_scoped_singleton_locks if k[0] == scope_key]
        for k in scoped_lock_keys:
            del self._sync_scoped_singleton_locks[k]
        async_scoped_lock_keys = [k for k in self._scoped_singleton_locks if k[0] == scope_key]
        for k in async_scoped_lock_keys:
            del self._scoped_singleton_locks[k]

    def _get_scoped_registration(
        self,
        service_key: ServiceKey,
        current_scope: ScopeId,
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

    def _get_registration(
        self,
        service_key: ServiceKey,
        current_scope: ScopeId | None,
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

        # Auto-register if enabled
        if not self._register_if_missing:
            raise DIWireServiceNotRegisteredError(service_key)

        registration = self._get_auto_registration(service_key=service_key)
        self._registry[service_key] = registration
        return registration

    def _get_cache_scope(
        self,
        current_scope: ScopeId | None,
        registered_scope: str | None,
    ) -> tuple[tuple[str | None, int], ...] | None:
        """Get the scope key to use for caching scoped instances.

        Returns the tuple key up to and including the registered scope segment.
        E.g., current=ScopeId((("request", 1), ("child", 2))), registered="request"
        -> (("request", 1),)
        """
        if current_scope is None:
            return None
        if registered_scope is None:
            return current_scope.segments

        # Find segments up to and including the registered scope name
        return current_scope.get_cache_key_for_scope(registered_scope)

    def _scope_matches(self, current_scope: ScopeId, registered_scope: str) -> bool:
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

        if not isinstance(service_key.value, type):
            raise DIWireNotAClassError(service_key)

        for base_cls, registration_factory in self._autoregister_registration_factories.items():
            if issubclass(service_key.value, base_cls):
                return registration_factory(service_key.value)

        return Registration(
            service_key=service_key,
            lifetime=self._autoregister_default_lifetime,
        )

    def _get_resolved_dependencies(self, service_key: ServiceKey) -> ResolvedDependencies:
        resolved_dependencies = ResolvedDependencies()

        dependencies = self._dependencies_extractor.get_dependencies_with_defaults(
            service_key=service_key,
        )
        for name, param_info in dependencies.items():
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
