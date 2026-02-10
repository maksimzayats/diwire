from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager, suppress
from dataclasses import dataclass
from types import TracebackType
from typing import (
    Any,
    Generic,
    Literal,
    TypeVar,
    cast,
    overload,
)

from diwire.exceptions import DIWireInvalidRegistrationError
from diwire.injection import (
    INJECT_RESOLVER_KWARG,
    INJECT_WRAPPER_MARKER,
    InjectedCallableInspector,
    InjectedParameter,
)
from diwire.lock_mode import LockMode
from diwire.providers import (
    ContextManagerProvider,
    FactoryProvider,
    GeneratorProvider,
    Lifetime,
    ProviderDependenciesExtractor,
    ProviderDependency,
    ProviderReturnTypeExtractor,
    ProviderSpec,
    ProvidersRegistrations,
)
from diwire.resolvers.manager import ResolversManager
from diwire.resolvers.protocol import ResolverProtocol
from diwire.scope import BaseScope, Scope
from diwire.validators import DependecyRegistrationValidator

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])
InjectableF = TypeVar("InjectableF", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


class Container:
    """A dependency injection container."""

    # Hot-path methods rebound to the compiled root resolver to keep steady-state
    # resolution/scope calls on generated fast paths.
    _ENTRYPOINT_METHOD_NAMES: tuple[str, ...] = (
        "resolve",
        "aresolve",
        "enter_scope",
    )

    def __init__(
        self,
        root_scope: BaseScope = Scope.APP,
        default_lifetime: Lifetime = Lifetime.TRANSIENT,
        *,
        lock_mode: LockMode | Literal["auto"] = "auto",
        autoregister: bool = False,
        autoregister_dependencies: bool = False,
    ) -> None:
        """Initialize the container with an optional configuration.

        Args:
            root_scope: The initial root scope for the container. All singleton providers will be tied to this scope. Defaults to Scope.APP.
            default_lifetime: The lifetime that will be used for providers if not specified. Defaults to Lifetime.TRANSIENT.
            lock_mode: Default lock strategy for non-instance registrations. Accepts LockMode or "auto". When set to "auto", sync-only graphs use thread locks and graphs containing async specs use async locks. Defaults to "auto".
            autoregister: Whether to automatically register dependencies when they are resolved if not already registered. Defaults to False.
            autoregister_dependencies: Whether to automatically register provider dependencies as concrete types during registration. Defaults to False.

        """
        self._root_scope = root_scope
        self._default_lifetime = default_lifetime
        self._lock_mode = lock_mode
        self._autoregister = autoregister
        self._autoregister_dependencies = autoregister_dependencies

        self._provider_dependencies_extractor = ProviderDependenciesExtractor()
        self._provider_return_type_extractor = ProviderReturnTypeExtractor()
        self._dependency_registration_validator = DependecyRegistrationValidator()
        self._providers_registrations = ProvidersRegistrations()
        self._resolvers_manager = ResolversManager()
        self._injected_callable_inspector = InjectedCallableInspector()

        self._root_resolver: ResolverProtocol | None = None
        self._container_entrypoints: dict[str, Callable[..., Any]] = {
            method_name: getattr(self, method_name) for method_name in self._ENTRYPOINT_METHOD_NAMES
        }

    # region Registration Methods
    def register_instance(
        self,
        provides: type[T] | None = None,
        *,
        instance: T,
    ) -> None:
        """Register an instance provider in the container.

        Instance providers always use ``LockMode.NONE``.
        """
        self._providers_registrations.add(
            ProviderSpec(
                provides=provides or type(instance),
                instance=instance,
                lifetime=self._default_lifetime,
                scope=self._root_scope,
                is_async=False,
                is_any_dependency_async=False,
                needs_cleanup=False,
                lock_mode=LockMode.NONE,
            ),
        )
        self._invalidate_compilation()

    def register_concrete(
        self,
        provides: type[T] | None = None,
        *,
        concrete_type: type[T] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | None = None,
    ) -> ConcreteTypeRegistrationDecorator[T]:
        """Register a concrete type provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator = ConcreteTypeRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        if provides is None and concrete_type is None:
            return decorator

        if provides is None:
            provides = concrete_type
        if concrete_type is None:
            concrete_type = provides

        if (
            provides is None or concrete_type is None
        ):  # pragma: no cover - normalized above; defensive invariant guard
            msg = "Concrete provider registration requires either provides or concrete_type."
            raise DIWireInvalidRegistrationError(msg)

        self._dependency_registration_validator.validate_concrete_type(concrete_type=concrete_type)

        dependencies_for_provider = self._resolve_concrete_registration_dependencies(
            concrete_type=concrete_type,
            explicit_dependencies=dependencies,
        )
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_scope = scope or self._root_scope
        resolved_lifetime = lifetime or self._default_lifetime

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                concrete_type=concrete_type,
                lifetime=resolved_lifetime,
                scope=resolved_scope,
                dependencies=dependencies_for_provider,
                is_async=False,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=False,
                lock_mode=self._resolve_provider_lock_mode(lock_mode),
            ),
        )
        self._autoregister_provider_dependencies(
            dependencies=dependencies_for_provider,
            scope=resolved_scope,
            lifetime=resolved_lifetime,
            enabled=self._resolve_autoregister_dependencies(autoregister_dependencies),
        )
        self._invalidate_compilation()

        return decorator

    def register_factory(
        self,
        provides: type[T] | None = None,
        *,
        factory: Callable[..., T] | Callable[..., Awaitable[T]] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | None = None,
    ) -> FactoryRegistrationDecorator[T]:
        """Register a factory provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator = FactoryRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        if factory is None:
            return decorator

        if provides is None:
            provides = self._provider_return_type_extractor.extract_from_factory(factory=factory)

        dependencies_for_provider = self._resolve_factory_registration_dependencies(
            factory=factory,
            explicit_dependencies=dependencies,
        )
        is_async = self._provider_return_type_extractor.is_factory_async(factory)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_scope = scope or self._root_scope
        resolved_lifetime = lifetime or self._default_lifetime

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                factory=factory,
                lifetime=resolved_lifetime,
                scope=resolved_scope,
                dependencies=dependencies_for_provider,
                is_async=is_async,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=False,
                lock_mode=self._resolve_provider_lock_mode(lock_mode),
            ),
        )
        self._autoregister_provider_dependencies(
            dependencies=dependencies_for_provider,
            scope=resolved_scope,
            lifetime=resolved_lifetime,
            enabled=self._resolve_autoregister_dependencies(autoregister_dependencies),
        )
        self._invalidate_compilation()

        return decorator

    def register_generator(
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
    ) -> GeneratorRegistrationDecorator[T]:
        """Register a generator provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator = GeneratorRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        if generator is None:
            return decorator

        if provides is None:
            provides = self._provider_return_type_extractor.extract_from_generator(
                generator=generator,
            )

        dependencies_for_provider = self._resolve_generator_registration_dependencies(
            generator=generator,
            explicit_dependencies=dependencies,
        )
        is_async = self._provider_return_type_extractor.is_generator_async(generator)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_scope = scope or self._root_scope
        resolved_lifetime = lifetime or self._default_lifetime

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                generator=generator,
                lifetime=resolved_lifetime,
                scope=resolved_scope,
                dependencies=dependencies_for_provider,
                is_async=is_async,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=True,
                lock_mode=self._resolve_provider_lock_mode(lock_mode),
            ),
        )
        self._autoregister_provider_dependencies(
            dependencies=dependencies_for_provider,
            scope=resolved_scope,
            lifetime=resolved_lifetime,
            enabled=self._resolve_autoregister_dependencies(autoregister_dependencies),
        )
        self._invalidate_compilation()

        return decorator

    def register_context_manager(
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
    ) -> ContextManagerRegistrationDecorator[T]:
        """Register a context manager provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator = ContextManagerRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        if context_manager is None:
            return decorator

        if provides is None:
            provides = self._provider_return_type_extractor.extract_from_context_manager(
                context_manager=context_manager,
            )

        dependencies_for_provider = self._resolve_context_manager_registration_dependencies(
            context_manager=context_manager,
            explicit_dependencies=dependencies,
        )
        is_async = self._provider_return_type_extractor.is_context_manager_async(context_manager)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_scope = scope or self._root_scope
        resolved_lifetime = lifetime or self._default_lifetime

        self._providers_registrations.add(
            ProviderSpec(
                provides=provides,
                context_manager=context_manager,
                lifetime=resolved_lifetime,
                scope=resolved_scope,
                dependencies=dependencies_for_provider,
                is_async=is_async,
                is_any_dependency_async=is_any_dependency_async,
                needs_cleanup=True,
                lock_mode=self._resolve_provider_lock_mode(lock_mode),
            ),
        )
        self._autoregister_provider_dependencies(
            dependencies=dependencies_for_provider,
            scope=resolved_scope,
            lifetime=resolved_lifetime,
            enabled=self._resolve_autoregister_dependencies(autoregister_dependencies),
        )
        self._invalidate_compilation()

        return decorator

    def _resolve_concrete_registration_dependencies(
        self,
        *,
        concrete_type: type[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_concrete_type(
                concrete_type=concrete_type,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_concrete_type(
            concrete_type=concrete_type,
            dependencies=explicit_dependencies,
        )

    def _resolve_factory_registration_dependencies(
        self,
        *,
        factory: FactoryProvider[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_factory(
                factory=factory,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_factory(
            factory=factory,
            dependencies=explicit_dependencies,
        )

    def _resolve_generator_registration_dependencies(
        self,
        *,
        generator: GeneratorProvider[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_generator(
                generator=generator,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_generator(
            generator=generator,
            dependencies=explicit_dependencies,
        )

    def _resolve_context_manager_registration_dependencies(
        self,
        *,
        context_manager: ContextManagerProvider[Any],
        explicit_dependencies: list[ProviderDependency] | None,
    ) -> list[ProviderDependency]:
        if explicit_dependencies is None:
            return self._provider_dependencies_extractor.extract_from_context_manager(
                context_manager=context_manager,
            )
        return self._provider_dependencies_extractor.validate_explicit_for_context_manager(
            context_manager=context_manager,
            dependencies=explicit_dependencies,
        )

    def _resolve_provider_lock_mode(
        self,
        lock_mode: LockMode | Literal["from_container"],
    ) -> LockMode | Literal["auto"]:
        if lock_mode == "from_container":
            return self._lock_mode

        return lock_mode

    def _resolve_autoregister_dependencies(self, autoregister_dependencies: bool | None) -> bool:
        if autoregister_dependencies is None:
            return self._autoregister_dependencies
        return autoregister_dependencies

    def _autoregister_provider_dependencies(
        self,
        *,
        dependencies: list[ProviderDependency],
        scope: BaseScope,
        lifetime: Lifetime,
        enabled: bool,
    ) -> None:
        if not enabled:
            return

        for dependency in dependencies:
            if self._providers_registrations.find_by_type(dependency.provides):
                continue
            with suppress(Exception):
                self.register_concrete(
                    concrete_type=dependency.provides,
                    scope=scope,
                    lifetime=lifetime,
                    autoregister_dependencies=True,
                )

    def _ensure_autoregistration(self, dependency: Any) -> None:
        if not self._autoregister:
            return

        if self._providers_registrations.find_by_type(dependency):
            return

        self.register_concrete(concrete_type=dependency)

    @overload
    def inject(
        self,
        func: InjectableF,
    ) -> InjectableF: ...

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
        """Decorate a callable to auto-inject parameters marked with Injected[T]."""

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
        if INJECT_RESOLVER_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved parameter "
                f"'{INJECT_RESOLVER_KWARG}'."
            )
            raise DIWireInvalidRegistrationError(msg)

        inspected_callable = self._injected_callable_inspector.inspect_callable(callable_obj)
        injected_parameters = inspected_callable.injected_parameters
        resolved_autoregister = self._resolve_autoregister_dependencies(autoregister_dependencies)
        if resolved_autoregister:
            self._autoregister_injected_dependencies(
                injected_parameters=injected_parameters,
                scope=scope,
            )

        inferred_scope_level = self._infer_injected_scope_level(
            injected_parameters=injected_parameters,
        )
        if scope is not None and scope.level < inferred_scope_level:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' scope level {scope.level} is "
                f"shallower than required dependency scope level {inferred_scope_level}."
            )
            raise DIWireInvalidRegistrationError(msg)

        if inspect.iscoroutinefunction(callable_obj):

            @functools.wraps(callable_obj)
            async def _async_injected(*args: Any, **kwargs: Any) -> Any:
                resolver = self._resolve_inject_resolver(kwargs)
                bound_arguments = signature.bind_partial(*args, **kwargs)
                for injected_parameter in injected_parameters:
                    if injected_parameter.name in bound_arguments.arguments:
                        continue
                    bound_arguments.arguments[injected_parameter.name] = await resolver.aresolve(
                        injected_parameter.dependency,
                    )
                async_callable = cast("Callable[..., Awaitable[Any]]", callable_obj)
                return await async_callable(*bound_arguments.args, **bound_arguments.kwargs)

            wrapped_callable: Callable[..., Any] = _async_injected
        else:

            @functools.wraps(callable_obj)
            def _sync_injected(*args: Any, **kwargs: Any) -> Any:
                resolver = self._resolve_inject_resolver(kwargs)
                bound_arguments = signature.bind_partial(*args, **kwargs)
                for injected_parameter in injected_parameters:
                    if injected_parameter.name in bound_arguments.arguments:
                        continue
                    bound_arguments.arguments[injected_parameter.name] = resolver.resolve(
                        injected_parameter.dependency,
                    )
                return callable_obj(*bound_arguments.args, **bound_arguments.kwargs)

            wrapped_callable = _sync_injected

        wrapped_callable.__signature__ = inspected_callable.public_signature  # type: ignore[attr-defined]
        wrapped_callable.__dict__[INJECT_WRAPPER_MARKER] = True
        return cast("InjectableF", wrapped_callable)

    def _resolve_injected_dependency(self, *, annotation: Any) -> Any | None:
        return self._injected_callable_inspector.resolve_injected_dependency(annotation=annotation)

    def _autoregister_injected_dependencies(
        self,
        *,
        injected_parameters: tuple[InjectedParameter, ...],
        scope: BaseScope | None,
    ) -> None:
        registration_scope = scope or self._root_scope
        for injected_parameter in injected_parameters:
            if self._providers_registrations.find_by_type(injected_parameter.dependency):
                continue
            with suppress(Exception):
                self.register_concrete(
                    concrete_type=injected_parameter.dependency,
                    scope=registration_scope,
                    lifetime=self._default_lifetime,
                    autoregister_dependencies=True,
                )

    def _infer_injected_scope_level(
        self,
        *,
        injected_parameters: tuple[InjectedParameter, ...],
    ) -> int:
        max_scope_level = self._root_scope.level
        cache: dict[Any, int] = {}
        for injected_parameter in injected_parameters:
            max_scope_level = max(
                max_scope_level,
                self._infer_dependency_scope_level(
                    dependency=injected_parameter.dependency,
                    cache=cache,
                    in_progress=set(),
                ),
            )
        return max_scope_level

    def _infer_dependency_scope_level(
        self,
        *,
        dependency: Any,
        cache: dict[Any, int],
        in_progress: set[Any],
    ) -> int:
        known_level = cache.get(dependency)
        if known_level is not None:
            return known_level

        spec = self._providers_registrations.find_by_type(dependency)
        if spec is None:
            return self._root_scope.level
        if dependency in in_progress:
            return spec.scope.level

        in_progress.add(dependency)
        max_scope_level = spec.scope.level
        for nested_dependency in spec.dependencies:
            max_scope_level = max(
                max_scope_level,
                self._infer_dependency_scope_level(
                    dependency=nested_dependency.provides,
                    cache=cache,
                    in_progress=in_progress,
                ),
            )
        in_progress.remove(dependency)
        cache[dependency] = max_scope_level
        return max_scope_level

    def _resolve_inject_resolver(self, kwargs: dict[str, Any]) -> ResolverProtocol:
        if INJECT_RESOLVER_KWARG in kwargs:
            return cast("ResolverProtocol", kwargs.pop(INJECT_RESOLVER_KWARG))
        return self.compile()

    def _callable_name(self, callable_obj: Callable[..., Any]) -> str:
        return getattr(callable_obj, "__qualname__", repr(callable_obj))

    # endregion Registration Methods

    # region Compilation
    def compile(self) -> ResolverProtocol:
        """Compile and cache the root resolver for current registrations.

        After compilation, entrypoints are rebounded to the root resolver instance, so
        steady-state resolution/scope operations skip container-level indirection.
        When autoregistration is enabled, methods stay container-bound, so each call
        can still register missing dependencies before resolution.
        """
        if self._root_resolver is None:
            self._root_resolver = self._resolvers_manager.build_root_resolver(
                root_scope=self._root_scope,
                registrations=self._providers_registrations,
            )
        if not self._autoregister:
            self._bind_container_entrypoints(target=self._root_resolver)

        return self._root_resolver

    def _invalidate_compilation(self) -> None:
        """Discard compiled resolver state and restore original container methods.

        Any registration mutation can change the resolver graph, so cached compiled
        entrypoints must be reverted back to container methods until recompilation.
        """
        self._root_resolver = None
        self._restore_container_entrypoints()

    def _bind_container_entrypoints(
        self,
        *,
        target: ResolverProtocol,
    ) -> None:
        """Bind selected container entrypoints directly to resolver-bound methods."""
        for method_name in self._ENTRYPOINT_METHOD_NAMES:
            setattr(self, method_name, getattr(target, method_name))

    def _restore_container_entrypoints(self) -> None:
        """Restore original container-bound entrypoint methods captured at init."""
        for method_name, method in self._container_entrypoints.items():
            setattr(self, method_name, method)

    # endregion Compilation

    # region Resolution and Scope Management

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        """Resolve the given dependency and return its instance.

        If autoregistration is enabled, it will automatically register the dependency if not already registered.
        """
        self._ensure_autoregistration(dependency)
        resolver = self.compile()

        return resolver.resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        """Resolve the given dependency asynchronously and return its instance.

        If autoregistration is enabled, it will automatically register the dependency if not already registered.
        """
        self._ensure_autoregistration(dependency)
        resolver = self.compile()

        return await resolver.aresolve(dependency)

    def enter_scope(self, scope: BaseScope | None = None) -> ResolverProtocol:
        """Enter a new scope and return a new resolver for that scope."""
        resolver = self.compile()
        return resolver.enter_scope(scope)

    def __enter__(self) -> ResolverProtocol:
        """Enter the resolver context."""
        resolver = self.compile()
        return resolver.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the resolver context and perform any necessary cleanup.

        Cleanup will happen ONLY if the resolver created resources that need to be cleaned up.
        Like context managers or generators.
        """
        if self._root_resolver is None:
            msg = "Container context exit called without a matching enter."
            raise RuntimeError(msg)

        return self._root_resolver.__exit__(exc_type, exc_value, traceback)

    def __aenter__(self) -> ResolverProtocol:
        """Asynchronously enter the resolver context."""
        resolver = self.compile()
        return resolver.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Asynchronously exit the resolver context and perform any necessary cleanup.

        Cleanup will happen ONLY if the resolver created resources that need to be cleaned up.
        Like context managers or generators.
        """
        if self._root_resolver is None:
            msg = "Container async context exit called without a matching enter."
            raise RuntimeError(msg)

        return await self._root_resolver.__aexit__(exc_type, exc_value, traceback)

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Close the container and perform any necessary cleanup.

        Cleanup will happen ONLY if the resolver created resources that need to be cleaned up.
        Like context managers or generators.
        """
        return self.__exit__(exc_type, exc_value, traceback)

    async def aclose(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Asynchronously close the container and perform any necessary cleanup.

        Cleanup will happen ONLY if the resolver created resources that need to be cleaned up.
        Like context managers or generators.
        """
        return await self.__aexit__(exc_type, exc_value, traceback)

    # endregion Resolution and Scope Management


@dataclass(slots=True, kw_only=True)
class ConcreteTypeRegistrationDecorator(Generic[T]):
    """A decorator for registering concrete type providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | None = None

    def __call__(self, concrete_type: type[T]) -> type[T]:
        """Register the concrete type provider in the container."""
        self.container.register_concrete(
            provides=self.provides,
            concrete_type=concrete_type,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
            lock_mode=self.lock_mode,
            autoregister_dependencies=self.autoregister_dependencies,
        )

        return concrete_type


@dataclass(slots=True, kw_only=True)
class FactoryRegistrationDecorator(Generic[T]):
    """A decorator for registering factory providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | None = None

    def __call__(self, factory: F) -> F:
        """Register the factory provider in the container."""
        self.container.register_factory(
            provides=self.provides,
            factory=factory,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
            lock_mode=self.lock_mode,
            autoregister_dependencies=self.autoregister_dependencies,
        )

        return factory


@dataclass(slots=True, kw_only=True)
class GeneratorRegistrationDecorator(Generic[T]):
    """A decorator for registering generator providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | None = None

    def __call__(self, generator: F) -> F:
        """Register the generator provider in the container."""
        self.container.register_generator(
            provides=self.provides,
            generator=generator,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
            lock_mode=self.lock_mode,
            autoregister_dependencies=self.autoregister_dependencies,
        )

        return generator


@dataclass(slots=True, kw_only=True)
class ContextManagerRegistrationDecorator(Generic[T]):
    """A decorator for registering context manager providers in the container."""

    container: Container
    scope: BaseScope | None
    lifetime: Lifetime | None
    provides: type[T] | None = None
    dependencies: list[ProviderDependency] | None = None
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | None = None

    def __call__(self, context_manager: F) -> F:
        """Register the context manager provider in the container."""
        self.container.register_context_manager(
            provides=self.provides,
            context_manager=context_manager,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
            lock_mode=self.lock_mode,
            autoregister_dependencies=self.autoregister_dependencies,
        )

        return context_manager
