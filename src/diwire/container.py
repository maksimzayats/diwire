from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from types import TracebackType
from typing import (
    Any,
    Generic,
    Literal,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

from diwire.autoregistration import ConcreteTypeAutoregistrationPolicy
from diwire.exceptions import DIWireError, DIWireInvalidRegistrationError, DIWireScopeMismatchError
from diwire.injection import (
    INJECT_CONTEXT_KWARG,
    INJECT_RESOLVER_KWARG,
    INJECT_WRAPPER_MARKER,
    ContextParameter,
    InjectedCallableInspector,
    InjectedParameter,
)
from diwire.integrations.pydantic_settings import is_pydantic_settings_subclass
from diwire.lock_mode import LockMode
from diwire.open_generics import OpenGenericRegistry, OpenGenericResolver
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
C = TypeVar("C", bound=type[Any])

logger = logging.getLogger(__name__)
_MISSING_CLOSED_GENERIC_INJECTION = object()


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
        default_lifetime: Lifetime = Lifetime.SCOPED,
        *,
        lock_mode: LockMode | Literal["auto"] = "auto",
        autoregister_concrete_types: bool = True,
        autoregister_dependencies: bool = True,
    ) -> None:
        """Initialize the container with an optional configuration.

        Args:
            root_scope: The initial root scope for the container. Root-scoped (singleton) cached providers are tied to this scope. Defaults to Scope.APP.
            default_lifetime: The lifetime that will be used for providers if not specified. Defaults to Lifetime.SCOPED.
            lock_mode: Default lock strategy for non-instance registrations. Accepts LockMode or "auto". When set to "auto", sync-only graphs use thread locks and graphs containing async specs use async locks. In mixed graphs this means auto-mode sync cached paths are not thread-locked unless you override to LockMode.THREAD. Defaults to "auto".
            autoregister_concrete_types: Whether to automatically register concrete types when they are resolved if not already registered. Defaults to True.
            autoregister_dependencies: Whether to automatically register provider dependencies as concrete types during registration. It will respect `autoregister_concrete_types` flag. Defaults to True.

        """
        self._root_scope = root_scope
        self._default_lifetime = default_lifetime
        self._lock_mode = lock_mode
        self._autoregister_concrete_types = autoregister_concrete_types
        self._autoregister_dependencies = autoregister_dependencies

        self._concrete_autoregistration_policy = ConcreteTypeAutoregistrationPolicy()
        self._provider_dependencies_extractor = ProviderDependenciesExtractor()
        self._provider_return_type_extractor = ProviderReturnTypeExtractor()
        self._dependency_registration_validator = DependecyRegistrationValidator()
        self._providers_registrations = ProvidersRegistrations()
        self._open_generic_registry = OpenGenericRegistry()
        self._resolvers_manager = ResolversManager()
        self._injected_callable_inspector = InjectedCallableInspector()

        self._root_resolver: ResolverProtocol | None = None
        self._graph_revision: int = 0
        self._registration_mutation_depth: int = 0
        self._registration_mutation_snapshot: _ContainerGraphSnapshot | None = None
        self._registration_mutation_failed: bool = False
        self._injected_scope_contracts: list[_InjectedScopeContract] = []
        self._container_entrypoints: dict[str, Callable[..., Any]] = {
            method_name: getattr(self, method_name) for method_name in self._ENTRYPOINT_METHOD_NAMES
        }

    # region Registration Methods
    def add_instance(
        self,
        instance: T,
        *,
        provides: Any | Literal["infer"] = "infer",
    ) -> None:
        """Register an instance provider in the container.

        Instance providers always use ``LockMode.NONE``.
        """
        provides_value = cast("Any", provides)
        if provides_value == "infer":
            resolved_provides: Any = type(instance)
        elif provides_value is not None:
            resolved_provides = provides_value
        else:
            msg = "add_instance() parameter 'provides' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        with self._registration_mutation():
            self._providers_registrations.add(
                ProviderSpec(
                    provides=resolved_provides,
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
    ) -> ConcreteTypeRegistrationDecorator[Any]: ...

    def add_concrete(
        self,
        concrete_type: type[Any] | Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | ConcreteTypeRegistrationDecorator[Any]:
        """Register a concrete type provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator: ConcreteTypeRegistrationDecorator[Any] = ConcreteTypeRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        if concrete_type == "from_decorator":
            return decorator

        resolved_provides, resolved_concrete_type = self._resolve_concrete_registration_types(
            provides=provides,
            concrete_type=concrete_type,
        )
        resolved_scope = self._resolve_registration_scope(
            scope=scope,
            method_name="add_concrete",
        )
        resolved_lifetime = self._resolve_registration_lifetime(
            lifetime=lifetime,
            method_name="add_concrete",
        )
        explicit_dependencies = self._resolve_registration_dependencies(
            dependencies=dependencies,
            method_name="add_concrete",
        )
        resolved_autoregister_dependencies = self._resolve_registration_autoregister_dependencies(
            autoregister_dependencies=autoregister_dependencies,
            method_name="add_concrete",
        )

        self._dependency_registration_validator.validate_concrete_type(
            concrete_type=resolved_concrete_type,
        )

        dependencies_for_provider = self._resolve_concrete_registration_dependencies(
            concrete_type=resolved_concrete_type,
            explicit_dependencies=explicit_dependencies,
        )
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_lock_mode = self._resolve_provider_lock_mode(lock_mode)

        with self._registration_mutation():
            if (
                self._open_generic_registry.register(
                    provides=resolved_provides,
                    provider_kind="concrete_type",
                    provider=resolved_concrete_type,
                    lifetime=resolved_lifetime,
                    scope=resolved_scope,
                    lock_mode=resolved_lock_mode,
                    is_async=False,
                    is_any_dependency_async=is_any_dependency_async,
                    needs_cleanup=False,
                    dependencies=dependencies_for_provider,
                )
                is not None
            ):
                self._autoregister_provider_dependencies(
                    dependencies=dependencies_for_provider,
                    scope=resolved_scope,
                    lifetime=resolved_lifetime,
                    enabled=self._resolve_autoregister_dependencies(
                        resolved_autoregister_dependencies,
                    ),
                )
                self._invalidate_compilation()
                return None

            (
                closed_generic_injections,
                dependencies_for_provider,
            ) = self._resolve_closed_concrete_generic_injections(
                provides=resolved_provides,
                dependencies=dependencies_for_provider,
            )
            is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
                dependencies_for_provider,
            )
            if closed_generic_injections:
                concrete_factory = self._build_closed_concrete_factory(
                    concrete_type=resolved_concrete_type,
                    injected_arguments=closed_generic_injections,
                )
                self._providers_registrations.add(
                    ProviderSpec(
                        provides=resolved_provides,
                        factory=concrete_factory,
                        lifetime=resolved_lifetime,
                        scope=resolved_scope,
                        dependencies=dependencies_for_provider,
                        is_async=False,
                        is_any_dependency_async=is_any_dependency_async,
                        needs_cleanup=False,
                        lock_mode=resolved_lock_mode,
                    ),
                )
                self._autoregister_provider_dependencies(
                    dependencies=dependencies_for_provider,
                    scope=resolved_scope,
                    lifetime=resolved_lifetime,
                    enabled=self._resolve_autoregister_dependencies(
                        resolved_autoregister_dependencies,
                    ),
                )
                self._invalidate_compilation()
                return None

            self._providers_registrations.add(
                ProviderSpec(
                    provides=resolved_provides,
                    concrete_type=resolved_concrete_type,
                    lifetime=resolved_lifetime,
                    scope=resolved_scope,
                    dependencies=dependencies_for_provider,
                    is_async=False,
                    is_any_dependency_async=is_any_dependency_async,
                    needs_cleanup=False,
                    lock_mode=resolved_lock_mode,
                ),
            )
            self._autoregister_provider_dependencies(
                dependencies=dependencies_for_provider,
                scope=resolved_scope,
                lifetime=resolved_lifetime,
                enabled=self._resolve_autoregister_dependencies(
                    resolved_autoregister_dependencies,
                ),
            )
            self._invalidate_compilation()

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
    ) -> FactoryRegistrationDecorator[Any]: ...

    def add_factory(
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
    ) -> None | FactoryRegistrationDecorator[Any]:
        """Register a factory provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator: FactoryRegistrationDecorator[Any] = FactoryRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        factory_value = cast("Any", factory)
        if factory_value == "from_decorator":
            return decorator

        if not callable(factory_value):
            msg = "add_factory() parameter 'factory' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)

        factory_provider = cast("FactoryProvider[Any]", factory_value)
        resolved_provides = self._resolve_registration_provides(
            provides=provides,
            method_name="add_factory",
            infer_from=lambda: self._provider_return_type_extractor.extract_from_factory(
                factory=factory_provider,
            ),
        )
        resolved_scope = self._resolve_registration_scope(
            scope=scope,
            method_name="add_factory",
        )
        resolved_lifetime = self._resolve_registration_lifetime(
            lifetime=lifetime,
            method_name="add_factory",
        )
        explicit_dependencies = self._resolve_registration_dependencies(
            dependencies=dependencies,
            method_name="add_factory",
        )
        resolved_autoregister_dependencies = self._resolve_registration_autoregister_dependencies(
            autoregister_dependencies=autoregister_dependencies,
            method_name="add_factory",
        )

        dependencies_for_provider = self._resolve_factory_registration_dependencies(
            factory=factory_provider,
            explicit_dependencies=explicit_dependencies,
        )
        is_async = self._provider_return_type_extractor.is_factory_async(factory_provider)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_lock_mode = self._resolve_provider_lock_mode(lock_mode)

        self._register_non_concrete_provider(
            provides=resolved_provides,
            provider_kind="factory",
            provider=factory_provider,
            provider_field="factory",
            lifetime=resolved_lifetime,
            scope=resolved_scope,
            lock_mode=resolved_lock_mode,
            is_async=is_async,
            is_any_dependency_async=is_any_dependency_async,
            needs_cleanup=False,
            dependencies=dependencies_for_provider,
            resolved_autoregister_dependencies=resolved_autoregister_dependencies,
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
    ) -> GeneratorRegistrationDecorator[Any]: ...

    def add_generator(
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
    ) -> None | GeneratorRegistrationDecorator[Any]:
        """Register a generator provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator: GeneratorRegistrationDecorator[Any] = GeneratorRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        generator_value = cast("Any", generator)
        if generator_value == "from_decorator":
            return decorator

        if not callable(generator_value):
            msg = "add_generator() parameter 'generator' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)

        generator_provider = cast("GeneratorProvider[Any]", generator_value)
        resolved_provides = self._resolve_registration_provides(
            provides=provides,
            method_name="add_generator",
            infer_from=lambda: self._provider_return_type_extractor.extract_from_generator(
                generator=generator_provider,
            ),
        )
        resolved_scope = self._resolve_registration_scope(
            scope=scope,
            method_name="add_generator",
        )
        resolved_lifetime = self._resolve_registration_lifetime(
            lifetime=lifetime,
            method_name="add_generator",
        )
        explicit_dependencies = self._resolve_registration_dependencies(
            dependencies=dependencies,
            method_name="add_generator",
        )
        resolved_autoregister_dependencies = self._resolve_registration_autoregister_dependencies(
            autoregister_dependencies=autoregister_dependencies,
            method_name="add_generator",
        )

        dependencies_for_provider = self._resolve_generator_registration_dependencies(
            generator=generator_provider,
            explicit_dependencies=explicit_dependencies,
        )
        is_async = self._provider_return_type_extractor.is_generator_async(generator_provider)
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_lock_mode = self._resolve_provider_lock_mode(lock_mode)

        self._register_non_concrete_provider(
            provides=resolved_provides,
            provider_kind="generator",
            provider=generator_provider,
            provider_field="generator",
            lifetime=resolved_lifetime,
            scope=resolved_scope,
            lock_mode=resolved_lock_mode,
            is_async=is_async,
            is_any_dependency_async=is_any_dependency_async,
            needs_cleanup=True,
            dependencies=dependencies_for_provider,
            resolved_autoregister_dependencies=resolved_autoregister_dependencies,
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
    ) -> ContextManagerRegistrationDecorator[Any]: ...

    def add_context_manager(
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
    ) -> None | ContextManagerRegistrationDecorator[Any]:
        """Register a context manager provider in the container.

        ``lock_mode="from_container"`` inherits the container-level mode.
        """
        decorator: ContextManagerRegistrationDecorator[Any] = ContextManagerRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            dependencies=dependencies,
            lock_mode=lock_mode,
            autoregister_dependencies=autoregister_dependencies,
        )

        context_manager_value = cast("Any", context_manager)
        if context_manager_value == "from_decorator":
            return decorator

        if not callable(context_manager_value):
            msg = (
                "add_context_manager() parameter 'context_manager' must be callable or "
                "'from_decorator'."
            )
            raise DIWireInvalidRegistrationError(msg)

        context_manager_provider = cast("ContextManagerProvider[Any]", context_manager_value)
        resolved_provides = self._resolve_registration_provides(
            provides=provides,
            method_name="add_context_manager",
            infer_from=lambda: self._provider_return_type_extractor.extract_from_context_manager(
                context_manager=context_manager_provider,
            ),
        )
        resolved_scope = self._resolve_registration_scope(
            scope=scope,
            method_name="add_context_manager",
        )
        resolved_lifetime = self._resolve_registration_lifetime(
            lifetime=lifetime,
            method_name="add_context_manager",
        )
        explicit_dependencies = self._resolve_registration_dependencies(
            dependencies=dependencies,
            method_name="add_context_manager",
        )
        resolved_autoregister_dependencies = self._resolve_registration_autoregister_dependencies(
            autoregister_dependencies=autoregister_dependencies,
            method_name="add_context_manager",
        )

        dependencies_for_provider = self._resolve_context_manager_registration_dependencies(
            context_manager=context_manager_provider,
            explicit_dependencies=explicit_dependencies,
        )
        is_async = self._provider_return_type_extractor.is_context_manager_async(
            context_manager_provider,
        )
        is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
            dependencies_for_provider,
        )

        resolved_lock_mode = self._resolve_provider_lock_mode(lock_mode)

        self._register_non_concrete_provider(
            provides=resolved_provides,
            provider_kind="context_manager",
            provider=context_manager_provider,
            provider_field="context_manager",
            lifetime=resolved_lifetime,
            scope=resolved_scope,
            lock_mode=resolved_lock_mode,
            is_async=is_async,
            is_any_dependency_async=is_any_dependency_async,
            needs_cleanup=True,
            dependencies=dependencies_for_provider,
            resolved_autoregister_dependencies=resolved_autoregister_dependencies,
        )
        return None

    def _resolve_concrete_registration_types(
        self,
        *,
        provides: Any | Literal["infer"],
        concrete_type: Any,
    ) -> tuple[Any, type[Any]]:
        provides_value = cast("Any", provides)
        concrete_type_value = concrete_type

        if provides_value == "infer":
            resolved_provides = concrete_type_value
        elif provides_value is not None:
            resolved_provides = provides_value
        else:
            msg = "add_concrete() parameter 'provides' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        if concrete_type_value is None:
            msg = "add_concrete() parameter 'concrete_type' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        return resolved_provides, concrete_type_value

    def _resolve_registration_provides(
        self,
        *,
        provides: Any,
        method_name: str,
        infer_from: Callable[[], Any],
    ) -> Any:
        if provides == "infer":
            return infer_from()
        if provides is not None:
            return provides

        msg = f"{method_name}() parameter 'provides' must not be None; use 'infer'."
        raise DIWireInvalidRegistrationError(msg)

    def _resolve_registration_scope(
        self,
        *,
        scope: BaseScope | Literal["from_container"],
        method_name: str,
    ) -> BaseScope:
        scope_value = cast("Any", scope)
        if scope_value == "from_container":
            return self._root_scope
        if isinstance(scope_value, BaseScope):
            return scope_value

        msg = f"{method_name}() parameter 'scope' must be BaseScope or 'from_container'."
        raise DIWireInvalidRegistrationError(msg)

    def _resolve_registration_lifetime(
        self,
        *,
        lifetime: Lifetime | Literal["from_container"],
        method_name: str,
    ) -> Lifetime:
        lifetime_value = cast("Any", lifetime)
        if lifetime_value == "from_container":
            return self._default_lifetime
        if isinstance(lifetime_value, Lifetime):
            return lifetime_value

        msg = f"{method_name}() parameter 'lifetime' must be Lifetime or 'from_container'."
        raise DIWireInvalidRegistrationError(msg)

    def _resolve_registration_dependencies(
        self,
        *,
        dependencies: list[ProviderDependency] | Literal["infer"],
        method_name: str,
    ) -> list[ProviderDependency] | None:
        dependencies_value = cast("Any", dependencies)
        if dependencies_value == "infer":
            return None
        if isinstance(dependencies_value, list):
            return cast("list[ProviderDependency]", dependencies_value)

        msg = f"{method_name}() parameter 'dependencies' must be a list or 'infer'."
        raise DIWireInvalidRegistrationError(msg)

    def _resolve_registration_autoregister_dependencies(
        self,
        *,
        autoregister_dependencies: bool | Literal["from_container"],
        method_name: str,
    ) -> bool | None:
        autoregister_dependencies_value = cast("Any", autoregister_dependencies)
        if autoregister_dependencies_value == "from_container":
            return None
        if isinstance(autoregister_dependencies_value, bool):
            return autoregister_dependencies_value

        msg = (
            f"{method_name}() parameter 'autoregister_dependencies' must be bool or "
            "'from_container'."
        )
        raise DIWireInvalidRegistrationError(msg)

    def _register_non_concrete_provider(
        self,
        *,
        provides: Any,
        provider_kind: Literal["factory", "generator", "context_manager"],
        provider: Any,
        provider_field: Literal["factory", "generator", "context_manager"],
        lifetime: Lifetime,
        scope: BaseScope,
        lock_mode: LockMode | Literal["auto"],
        is_async: bool,
        is_any_dependency_async: bool,
        needs_cleanup: bool,
        dependencies: list[ProviderDependency],
        resolved_autoregister_dependencies: bool | None,
    ) -> None:
        with self._registration_mutation():
            if (
                self._open_generic_registry.register(
                    provides=provides,
                    provider_kind=provider_kind,
                    provider=provider,
                    lifetime=lifetime,
                    scope=scope,
                    lock_mode=lock_mode,
                    is_async=is_async,
                    is_any_dependency_async=is_any_dependency_async,
                    needs_cleanup=needs_cleanup,
                    dependencies=dependencies,
                )
                is not None
            ):
                self._autoregister_provider_dependencies(
                    dependencies=dependencies,
                    scope=scope,
                    lifetime=lifetime,
                    enabled=self._resolve_autoregister_dependencies(
                        resolved_autoregister_dependencies,
                    ),
                )
                self._invalidate_compilation()
                return

            if provider_field == "factory":
                provider_spec = ProviderSpec(
                    provides=provides,
                    factory=cast("FactoryProvider[Any]", provider),
                    lifetime=lifetime,
                    scope=scope,
                    dependencies=dependencies,
                    is_async=is_async,
                    is_any_dependency_async=is_any_dependency_async,
                    needs_cleanup=needs_cleanup,
                    lock_mode=lock_mode,
                )
            elif provider_field == "generator":
                provider_spec = ProviderSpec(
                    provides=provides,
                    generator=cast("GeneratorProvider[Any]", provider),
                    lifetime=lifetime,
                    scope=scope,
                    dependencies=dependencies,
                    is_async=is_async,
                    is_any_dependency_async=is_any_dependency_async,
                    needs_cleanup=needs_cleanup,
                    lock_mode=lock_mode,
                )
            else:
                provider_spec = ProviderSpec(
                    provides=provides,
                    context_manager=cast("ContextManagerProvider[Any]", provider),
                    lifetime=lifetime,
                    scope=scope,
                    dependencies=dependencies,
                    is_async=is_async,
                    is_any_dependency_async=is_any_dependency_async,
                    needs_cleanup=needs_cleanup,
                    lock_mode=lock_mode,
                )

            self._providers_registrations.add(provider_spec)
            self._autoregister_provider_dependencies(
                dependencies=dependencies,
                scope=scope,
                lifetime=lifetime,
                enabled=self._resolve_autoregister_dependencies(
                    resolved_autoregister_dependencies,
                ),
            )
            self._invalidate_compilation()
            return

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

    def _resolve_closed_concrete_generic_injections(
        self,
        *,
        provides: Any,
        dependencies: list[ProviderDependency],
    ) -> tuple[dict[str, Any], list[ProviderDependency]]:
        typevar_map = self._closed_generic_typevar_map(provides=provides)
        if not typevar_map:
            return {}, dependencies

        injected_arguments: dict[str, Any] = {}
        remaining_dependencies: list[ProviderDependency] = []
        for dependency in dependencies:
            injection_value = self._resolve_closed_generic_injection_value(
                dependency_annotation=dependency.provides,
                typevar_map=typevar_map,
            )
            if injection_value is _MISSING_CLOSED_GENERIC_INJECTION:
                remaining_dependencies.append(dependency)
                continue
            injected_arguments[dependency.parameter.name] = injection_value

        return injected_arguments, remaining_dependencies

    def _closed_generic_typevar_map(self, *, provides: Any) -> dict[TypeVar, Any]:
        origin = get_origin(provides)
        if origin is None:
            return {}

        arguments = get_args(provides)
        if not arguments:
            return {}

        origin_typevars = tuple(
            parameter
            for parameter in getattr(origin, "__parameters__", ())
            if isinstance(parameter, TypeVar)
        )
        if len(origin_typevars) != len(arguments):
            return {}

        return dict(zip(origin_typevars, arguments, strict=True))

    def _resolve_closed_generic_injection_value(
        self,
        *,
        dependency_annotation: Any,
        typevar_map: dict[TypeVar, Any],
    ) -> Any:
        if isinstance(dependency_annotation, TypeVar):
            return typevar_map.get(dependency_annotation, _MISSING_CLOSED_GENERIC_INJECTION)

        origin = get_origin(dependency_annotation)
        arguments = get_args(dependency_annotation)
        if origin is type and len(arguments) == 1 and isinstance(arguments[0], TypeVar):
            return typevar_map.get(arguments[0], _MISSING_CLOSED_GENERIC_INJECTION)

        return _MISSING_CLOSED_GENERIC_INJECTION

    def _build_closed_concrete_factory(
        self,
        *,
        concrete_type: type[Any],
        injected_arguments: dict[str, Any],
    ) -> Callable[..., Any]:
        constructor_signature = inspect.signature(concrete_type)
        factory_injected_arguments = dict(injected_arguments)

        def _factory(*args: Any, **kwargs: Any) -> Any:
            bound_arguments = constructor_signature.bind_partial(*args, **kwargs)
            for argument_name, argument_value in factory_injected_arguments.items():
                if argument_name in bound_arguments.arguments:
                    continue
                bound_arguments.arguments[argument_name] = argument_value
            return concrete_type(*bound_arguments.args, **bound_arguments.kwargs)

        return _factory

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

    def _resolve_autoregister_dependencies(
        self,
        autoregister_dependencies: bool | None,
    ) -> bool:
        if not self._autoregister_concrete_types:
            return False
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
            with suppress(DIWireError):
                self._autoregister_dependency(
                    dependency=dependency.provides,
                    scope=scope,
                    lifetime=lifetime,
                    autoregister_dependencies=True,
                )

    def _autoregister_dependency(
        self,
        *,
        dependency: Any,
        scope: BaseScope,
        lifetime: Lifetime,
        autoregister_dependencies: bool,
    ) -> None:
        if is_pydantic_settings_subclass(dependency):
            # Settings are environment-backed configuration objects and should be
            # auto-registered as root-scoped (singleton) values via a no-arg factory.
            self.add_factory(
                lambda dependency_type=dependency: dependency_type(),
                provides=dependency,
                scope=self._root_scope,
                lifetime=Lifetime.SCOPED,
                autoregister_dependencies=autoregister_dependencies,
            )
            return

        if not self._concrete_autoregistration_policy.is_eligible_concrete(dependency):
            return

        self.add_concrete(
            dependency,
            scope=scope,
            lifetime=lifetime,
            autoregister_dependencies=autoregister_dependencies,
        )

    def _ensure_autoregistration(self, dependency: Any) -> None:
        if not self._autoregister_concrete_types:
            return

        if self._providers_registrations.find_by_type(dependency):
            return
        if self._open_generic_registry.has_match_for_dependency(dependency):
            return

        self._autoregister_dependency(
            dependency=dependency,
            scope=self._root_scope,
            lifetime=self._default_lifetime,
            autoregister_dependencies=True,
        )

    @overload
    def inject(
        self,
        func: InjectableF,
    ) -> InjectableF: ...

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
        """Decorate a callable to auto-inject parameters marked with Injected[T]."""
        scope_value = cast("Any", scope)
        resolved_scope: BaseScope | None
        if scope_value == "infer":
            resolved_scope = None
        elif isinstance(scope_value, BaseScope):
            resolved_scope = scope_value
        else:
            msg = "inject() parameter 'scope' must be BaseScope or 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        autoregister_dependencies_value = cast("Any", autoregister_dependencies)
        resolved_autoregister_dependencies: bool | None
        if autoregister_dependencies_value == "from_container":
            resolved_autoregister_dependencies = None
        elif isinstance(autoregister_dependencies_value, bool):
            resolved_autoregister_dependencies = autoregister_dependencies_value
        else:
            msg = "inject() parameter 'autoregister_dependencies' must be bool or 'from_container'."
            raise DIWireInvalidRegistrationError(msg)

        def decorator(callable_obj: InjectableF) -> InjectableF:
            return self._inject_callable(
                callable_obj=callable_obj,
                scope=resolved_scope,
                autoregister_dependencies=resolved_autoregister_dependencies,
                auto_open_scope=auto_open_scope,
            )

        func_value = cast("Any", func)
        if func_value == "from_decorator":
            return decorator
        if not callable(func_value):
            msg = "inject() parameter 'func' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)
        return decorator(func_value)

    def _inject_callable(
        self,
        *,
        callable_obj: InjectableF,
        scope: BaseScope | None,
        autoregister_dependencies: bool | None,
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
        injected_parameters = inspected_callable.injected_parameters
        context_parameters = inspected_callable.context_parameters
        resolved_autoregister = self._resolve_autoregister_dependencies(
            autoregister_dependencies,
        )
        if resolved_autoregister:
            self._autoregister_injected_dependencies(
                injected_parameters=injected_parameters,
                scope=scope,
            )

        inferred_scope_level = self._infer_injected_scope_level(
            injected_parameters=injected_parameters,
        )
        callable_name = self._callable_name(callable_obj)
        if scope is not None and scope.level < inferred_scope_level:
            msg = (
                f"Callable '{callable_name}' scope level {scope.level} is "
                f"shallower than required dependency scope level {inferred_scope_level}."
            )
            raise DIWireInvalidRegistrationError(msg)

        if scope is not None:
            self._injected_scope_contracts.append(
                _InjectedScopeContract(
                    callable_name=callable_name,
                    injected_parameters=injected_parameters,
                    scope=scope,
                ),
            )

        get_target_scope = self._build_injected_target_scope_getter(
            explicit_scope=scope,
            inferred_scope_level=inferred_scope_level,
            injected_parameters=injected_parameters,
            callable_name=callable_name,
            auto_open_scope=auto_open_scope,
        )

        if inspect.iscoroutinefunction(callable_obj):

            @functools.wraps(callable_obj)
            async def _async_injected(*args: Any, **kwargs: Any) -> Any:
                context = self._pop_inject_context(kwargs)
                base_resolver = self._resolve_inject_resolver(kwargs)
                target_scope = get_target_scope()
                maybe_scoped, scope_opened = self._enter_scope_if_needed(
                    base_resolver=base_resolver,
                    target_scope=target_scope,
                    context=context,
                )
                self._validate_inject_context_usage(
                    context=context,
                    scope_opened=scope_opened,
                )

                if maybe_scoped is base_resolver:
                    bound_arguments = await self._resolve_async_injected_arguments(
                        resolver=maybe_scoped,
                        signature=signature,
                        args=args,
                        kwargs=kwargs,
                        injected_parameters=injected_parameters,
                        context_parameters=context_parameters,
                    )
                    async_callable = cast("Callable[..., Awaitable[Any]]", callable_obj)
                    return await async_callable(*bound_arguments.args, **bound_arguments.kwargs)

                async_scoped_resolver = cast("Any", maybe_scoped)
                async with async_scoped_resolver:
                    bound_arguments = await self._resolve_async_injected_arguments(
                        resolver=maybe_scoped,
                        signature=signature,
                        args=args,
                        kwargs=kwargs,
                        injected_parameters=injected_parameters,
                        context_parameters=context_parameters,
                    )
                    async_callable = cast("Callable[..., Awaitable[Any]]", callable_obj)
                    return await async_callable(*bound_arguments.args, **bound_arguments.kwargs)

            wrapped_callable: Callable[..., Any] = _async_injected
        else:

            @functools.wraps(callable_obj)
            def _sync_injected(*args: Any, **kwargs: Any) -> Any:
                context = self._pop_inject_context(kwargs)
                base_resolver = self._resolve_inject_resolver(kwargs)
                target_scope = get_target_scope()
                maybe_scoped, scope_opened = self._enter_scope_if_needed(
                    base_resolver=base_resolver,
                    target_scope=target_scope,
                    context=context,
                )
                self._validate_inject_context_usage(
                    context=context,
                    scope_opened=scope_opened,
                )

                if maybe_scoped is base_resolver:
                    bound_arguments = self._resolve_sync_injected_arguments(
                        resolver=maybe_scoped,
                        signature=signature,
                        args=args,
                        kwargs=kwargs,
                        injected_parameters=injected_parameters,
                        context_parameters=context_parameters,
                    )
                    return callable_obj(*bound_arguments.args, **bound_arguments.kwargs)

                with maybe_scoped:
                    bound_arguments = self._resolve_sync_injected_arguments(
                        resolver=maybe_scoped,
                        signature=signature,
                        args=args,
                        kwargs=kwargs,
                        injected_parameters=injected_parameters,
                        context_parameters=context_parameters,
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
            with suppress(DIWireError):
                self._autoregister_dependency(
                    dependency=injected_parameter.dependency,
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
            open_match = self._open_generic_registry.find_best_match(dependency)
            if open_match is not None:
                return open_match.spec.scope.level
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

    def _resolve_sync_injected_arguments(
        self,
        *,
        resolver: ResolverProtocol,
        signature: inspect.Signature,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        injected_parameters: tuple[InjectedParameter, ...],
        context_parameters: tuple[ContextParameter, ...],
    ) -> inspect.BoundArguments:
        bound_arguments = signature.bind_partial(*args, **kwargs)
        for injected_parameter in injected_parameters:
            if injected_parameter.name in bound_arguments.arguments:
                continue
            bound_arguments.arguments[injected_parameter.name] = resolver.resolve(
                injected_parameter.dependency,
            )
        for context_parameter in context_parameters:
            if context_parameter.name in bound_arguments.arguments:
                continue
            bound_arguments.arguments[context_parameter.name] = resolver.resolve(
                context_parameter.dependency,
            )
        return bound_arguments

    async def _resolve_async_injected_arguments(
        self,
        *,
        resolver: ResolverProtocol,
        signature: inspect.Signature,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        injected_parameters: tuple[InjectedParameter, ...],
        context_parameters: tuple[ContextParameter, ...],
    ) -> inspect.BoundArguments:
        bound_arguments = signature.bind_partial(*args, **kwargs)
        for injected_parameter in injected_parameters:
            if injected_parameter.name in bound_arguments.arguments:
                continue
            bound_arguments.arguments[injected_parameter.name] = await resolver.aresolve(
                injected_parameter.dependency,
            )
        for context_parameter in context_parameters:
            if context_parameter.name in bound_arguments.arguments:
                continue
            bound_arguments.arguments[context_parameter.name] = await resolver.aresolve(
                context_parameter.dependency,
            )
        return bound_arguments

    def _resolve_inject_resolver(self, kwargs: dict[str, Any]) -> ResolverProtocol:
        if INJECT_RESOLVER_KWARG in kwargs:
            return cast("ResolverProtocol", kwargs.pop(INJECT_RESOLVER_KWARG))
        return self.compile()

    def _pop_inject_context(self, kwargs: dict[str, Any]) -> Mapping[Any, Any] | None:
        if INJECT_CONTEXT_KWARG not in kwargs:
            return None
        context = kwargs.pop(INJECT_CONTEXT_KWARG)
        if context is None:
            return None
        if isinstance(context, Mapping):
            return context
        msg = f"'{INJECT_CONTEXT_KWARG}' must be a mapping or None."
        raise DIWireInvalidRegistrationError(msg)

    def _validate_inject_context_usage(
        self,
        *,
        context: Mapping[Any, Any] | None,
        scope_opened: bool,
    ) -> None:
        if context is None or scope_opened:
            return
        msg = (
            f"`{INJECT_CONTEXT_KWARG}` was provided but no new scope was opened; pass "
            "`scope=...` to `inject(...)` or provide a resolver that was already created with "
            "context."
        )
        raise DIWireInvalidRegistrationError(msg)

    def _build_injected_target_scope_getter(
        self,
        *,
        explicit_scope: BaseScope | None,
        inferred_scope_level: int,
        injected_parameters: tuple[InjectedParameter, ...],
        callable_name: str,
        auto_open_scope: bool,
    ) -> Callable[[], BaseScope | None]:
        if not auto_open_scope:

            def _no_scope() -> BaseScope | None:
                return None

            return _no_scope
        if explicit_scope is not None:

            def _explicit_scope() -> BaseScope:
                return explicit_scope

            return _explicit_scope

        revision = self._graph_revision
        inferred_scope = self._find_scope_by_level(scope_level=inferred_scope_level)
        cached_target_scope = inferred_scope

        def _resolve_target_scope() -> BaseScope:
            nonlocal cached_target_scope, revision

            # Registrations can be mutated after decoration time (including after the wrapper is created),
            # so infer target scope lazily on call and re-check when the graph revision changes.
            if cached_target_scope is not None and revision == self._graph_revision:
                return cached_target_scope

            current_inferred_level = self._infer_injected_scope_level(
                injected_parameters=injected_parameters,
            )
            candidate = self._find_scope_by_level(scope_level=current_inferred_level)
            if candidate is None:
                msg = (
                    f"Callable '{callable_name}' inferred scope level {current_inferred_level} has no "
                    "matching scope in the root scope owner."
                )
                raise DIWireInvalidRegistrationError(msg)

            revision = self._graph_revision
            cached_target_scope = candidate
            return candidate

        return _resolve_target_scope

    def _find_scope_by_level(self, *, scope_level: int) -> BaseScope | None:
        return next(
            (candidate for candidate in self._root_scope.owner() if candidate.level == scope_level),
            None,
        )

    def _enter_scope_if_needed(
        self,
        *,
        base_resolver: ResolverProtocol,
        target_scope: BaseScope | None,
        context: Mapping[Any, Any] | None,
    ) -> tuple[ResolverProtocol, bool]:
        if target_scope is None:
            return base_resolver, False
        if target_scope.level == self._root_scope.level:
            return base_resolver, False
        try:
            if context is None:
                return base_resolver.enter_scope(target_scope), True
            try:
                return base_resolver.enter_scope(target_scope, context=context), True
            except TypeError as error:
                msg = (
                    "Resolver does not support context-aware scope entry. "
                    "Provide a DIWire resolver instance or omit "
                    f"'{INJECT_CONTEXT_KWARG}'."
                )
                raise DIWireInvalidRegistrationError(msg) from error
        except DIWireScopeMismatchError as error:
            if self._is_already_deep_enough_scope_error(error):
                return base_resolver, False
            raise

    @staticmethod
    def _is_already_deep_enough_scope_error(error: DIWireScopeMismatchError) -> bool:
        message = str(error)
        return message.startswith("Cannot enter scope level ") and " from level " in message

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
            root_resolver = self._resolvers_manager.build_root_resolver(
                root_scope=self._root_scope,
                registrations=self._providers_registrations,
            )
            if self._open_generic_registry.has_specs():
                has_async_specs = any(
                    spec.is_async for spec in self._providers_registrations.values()
                ) or any(spec.is_async for spec in self._open_generic_registry.values())
                root_resolver = cast(
                    "ResolverProtocol",
                    OpenGenericResolver(
                        base_resolver=root_resolver,
                        registry=self._open_generic_registry,
                        root_scope=self._root_scope,
                        has_async_specs=has_async_specs,
                        scope_level=self._root_scope.level,
                    ),
                )
            self._root_resolver = root_resolver
        if not self._autoregister_concrete_types:
            self._bind_container_entrypoints(target=self._root_resolver)

        return self._root_resolver

    def _invalidate_compilation(self) -> None:
        """Discard compiled resolver state and restore original container methods.

        Any registration mutation can change the resolver graph, so cached compiled
        entrypoints must be reverted back to container methods until recompilation.
        """
        self._graph_revision += 1
        self._root_resolver = None
        self._restore_container_entrypoints()

    def _revalidate_injected_scope_contracts(self) -> None:
        for contract in self._injected_scope_contracts:
            inferred_scope_level = self._infer_injected_scope_level(
                injected_parameters=contract.injected_parameters,
            )
            if contract.scope.level < inferred_scope_level:
                msg = (
                    f"Callable '{contract.callable_name}' scope level {contract.scope.level} is "
                    f"shallower than required dependency scope level {inferred_scope_level}."
                )
                raise DIWireInvalidRegistrationError(msg)

    @contextmanager
    def _registration_mutation(self) -> Generator[None, None, None]:
        if self._registration_mutation_depth == 0:
            self._registration_mutation_snapshot = _ContainerGraphSnapshot(
                providers_registrations=self._providers_registrations.snapshot(),
                open_generic_registry=self._open_generic_registry.snapshot(),
            )
            self._registration_mutation_failed = False

        self._registration_mutation_depth += 1
        try:
            yield
            if self._registration_mutation_depth == 1:
                self._revalidate_injected_scope_contracts()
        except DIWireInvalidRegistrationError:
            self._registration_mutation_failed = True
            raise
        finally:
            self._registration_mutation_depth -= 1
            if self._registration_mutation_depth == 0:
                if self._registration_mutation_failed:
                    snapshot = cast("_ContainerGraphSnapshot", self._registration_mutation_snapshot)
                    self._providers_registrations.restore(snapshot.providers_registrations)
                    self._open_generic_registry.restore(snapshot.open_generic_registry)
                    self._invalidate_compilation()
                self._registration_mutation_snapshot = None
                self._registration_mutation_failed = False

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

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
        """Enter a new scope and return a new resolver for that scope."""
        resolver = self.compile()
        return resolver.enter_scope(scope, context=context)

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
    scope: BaseScope | Literal["from_container"] = "from_container"
    lifetime: Lifetime | Literal["from_container"] = "from_container"
    provides: Any | Literal["infer"] = "infer"
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, concrete_type: C) -> C:
        """Register the concrete type provider in the container."""
        self.container.add_concrete(
            concrete_type,
            provides=self.provides,
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
    scope: BaseScope | Literal["from_container"] = "from_container"
    lifetime: Lifetime | Literal["from_container"] = "from_container"
    provides: Any | Literal["infer"] = "infer"
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, factory: F) -> F:
        """Register the factory provider in the container."""
        self.container.add_factory(
            factory,
            provides=self.provides,
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
    scope: BaseScope | Literal["from_container"] = "from_container"
    lifetime: Lifetime | Literal["from_container"] = "from_container"
    provides: Any | Literal["infer"] = "infer"
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, generator: F) -> F:
        """Register the generator provider in the container."""
        self.container.add_generator(
            generator,
            provides=self.provides,
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
    scope: BaseScope | Literal["from_container"] = "from_container"
    lifetime: Lifetime | Literal["from_container"] = "from_container"
    provides: Any | Literal["infer"] = "infer"
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, context_manager: F) -> F:
        """Register the context manager provider in the container."""
        self.container.add_context_manager(
            context_manager,
            provides=self.provides,
            scope=self.scope,
            lifetime=self.lifetime,
            dependencies=self.dependencies,
            lock_mode=self.lock_mode,
            autoregister_dependencies=self.autoregister_dependencies,
        )

        return context_manager


@dataclass(frozen=True, slots=True)
class _InjectedScopeContract:
    callable_name: str
    injected_parameters: tuple[InjectedParameter, ...]
    scope: BaseScope


@dataclass(frozen=True, slots=True)
class _ContainerGraphSnapshot:
    providers_registrations: ProvidersRegistrations.Snapshot
    open_generic_registry: OpenGenericRegistry.Snapshot
