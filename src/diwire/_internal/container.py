from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from types import TracebackType
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

from diwire._internal.autoregistration import ConcreteTypeAutoregistrationPolicy
from diwire._internal.injection import (
    INJECT_CONTEXT_KWARG,
    INJECT_RESOLVER_KWARG,
    INJECT_WRAPPER_MARKER,
    ContextParameter,
    InjectedCallableInspector,
    InjectedParameter,
)
from diwire._internal.integrations.pydantic_settings import is_pydantic_settings_subclass
from diwire._internal.lock_mode import LockMode
from diwire._internal.markers import (
    Component,
    ProviderMarker,
    build_annotated_key,
    component_base_key,
    is_all_annotation,
    is_from_context_annotation,
    is_maybe_annotation,
    is_provider_annotation,
    strip_all_annotation,
    strip_maybe_annotation,
    strip_provider_annotation,
)
from diwire._internal.open_generics import (
    OpenGenericRegistry,
    OpenGenericResolver,
    canonicalize_open_key,
)
from diwire._internal.providers import (
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
from diwire._internal.resolvers.manager import ResolversManager
from diwire._internal.resolvers.protocol import ResolverProtocol
from diwire._internal.scope import BaseScope, Scope
from diwire._internal.validators import DependecyRegistrationValidator
from diwire.exceptions import (
    DIWireDependencyNotRegisteredError,
    DIWireError,
    DIWireInvalidRegistrationError,
    DIWireScopeMismatchError,
)

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])
InjectableF = TypeVar("InjectableF", bound=Callable[..., Any])
C = TypeVar("C", bound=type[Any])

logger = logging.getLogger(__name__)
_MISSING_CLOSED_GENERIC_INJECTION = object()


class Container:
    """Manage dependency registration, resolution, scoping, and cleanup.

    Dependency keys are usually concrete types, protocols, or
    ``typing.Annotated`` tokens (for example ``Annotated[Db, Component("ro")]``).
    Closed generic keys are also supported when matching open-generic
    registrations.

    Use registrations for explicit control, or keep autoregistration enabled to
    auto-wire eligible concrete classes and their dependencies. Disable
    autoregistration for strict mode where every dependency must be registered
    explicitly.

    Resolution happens through a compiled resolver graph. ``resolve`` runs sync
    graphs, ``aresolve`` runs async graphs, and ``enter_scope`` creates nested
    resolvers that own scoped caches and cleanup callbacks. Registration
    mutations invalidate compilation automatically.
    """

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
        """Initialize a container and configure default registration behavior.

        Choose strict mode by setting ``autoregister_concrete_types=False``.
        Keep defaults for auto-wiring behavior. ``lock_mode="auto"`` selects
        thread locks for sync-only cached paths and async locks when async
        resolution paths are present.

        Args:
            root_scope: Root scope for resolver ownership and root-scoped caches.
            default_lifetime: Default lifetime used by registrations that omit
                ``lifetime``.
            lock_mode: Container default lock strategy for non-instance
                registrations. Accepts ``LockMode`` or ``"auto"``.
            autoregister_concrete_types: Enable on-demand concrete type
                autoregistration during resolution.
            autoregister_dependencies: Enable autoregistration of provider
                dependencies discovered at registration time.

        Notes:
            Common presets are: default mode (both autoregistration flags
            enabled), strict mode (both disabled), and mixed mode (concrete
            autoregistration enabled with dependency autoregistration disabled).

        Examples:
            .. code-block:: python

                container = Container()

                strict_container = Container(
                    autoregister_concrete_types=False,
                    autoregister_dependencies=False,
                )

                threaded_container = Container(lock_mode=LockMode.THREAD)

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
        self._decoration_rules_by_provides: dict[Any, list[_DecorationRule]] = {}
        self._decoration_chain_by_provides: dict[Any, _DecorationChain] = {}
        self._decoration_counter: int = 0
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
        component: object | None = None,
    ) -> None:
        """Register a pre-built instance as a provider.

        This is the simplest way to bind configuration objects or singleton
        clients. Re-registering the same dependency key overrides the previous
        spec.

        Args:
            instance: Instance value to return on resolution.
            provides: Dependency key to bind. Use ``"infer"`` to bind by
                ``type(instance)``.
            component: Optional component marker value used to register under
                ``Annotated[provides, Component(...)]``.

        Raises:
            DIWireInvalidRegistrationError: If ``provides`` is ``None``.

        Notes:
            Instance specs always use ``LockMode.NONE`` because value creation is
            not deferred.

        Examples:
            .. code-block:: python

                settings = Settings(api_url="https://api.example.com")
                container.add_instance(settings)

                resolved = container.resolve(Settings)

        """
        provides_value = cast("Any", provides)
        if provides_value == "infer":
            resolved_provides: Any = type(instance)
        elif provides_value is not None:
            resolved_provides = provides_value
        else:
            msg = "add_instance() parameter 'provides' must not be None; use 'infer'."
            raise DIWireInvalidRegistrationError(msg)

        resolved_provides_with_component = self._resolve_registration_component_provides(
            provides=resolved_provides,
            component=component,
            method_name="add_instance",
        )
        registration_provides, has_decoration_chain = self._resolve_registration_target_provides(
            resolved_provides_with_component,
        )

        with self._registration_mutation():
            self._providers_registrations.add(
                ProviderSpec(
                    provides=registration_provides,
                    instance=instance,
                    lifetime=self._default_lifetime,
                    scope=self._root_scope,
                    is_async=False,
                    is_any_dependency_async=False,
                    needs_cleanup=False,
                    lock_mode=LockMode.NONE,
                ),
            )
            self._finalize_registration_after_binding(
                original_provides=resolved_provides_with_component,
                has_decoration_chain=has_decoration_chain,
            )

    @overload
    def add_concrete(
        self,
        concrete_type: type[Any],
        *,
        provides: Any | Literal["infer"] = "infer",
        component: object | None = None,
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
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> ConcreteTypeRegistrationDecorator[Any]: ...

    def add_concrete(
        self,
        concrete_type: type[Any] | Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | ConcreteTypeRegistrationDecorator[Any]:
        """Register a concrete type provider.

        Supports direct calls and decorator form. ``provides`` may be a protocol,
        concrete type, annotated token, or open generic key. Dependencies are
        inferred from constructor annotations unless explicit dependencies are
        passed.

        Args:
            concrete_type: Concrete class to instantiate, or ``"from_decorator"``
                to return a decorator.
            provides: Dependency key produced by this provider. ``"infer"`` uses
                ``concrete_type`` directly.
            component: Optional component marker value used to register under
                ``Annotated[provides, Component(...)]``.
            scope: Provider scope, or ``"from_container"`` to inherit root scope.
            lifetime: Provider lifetime, or ``"from_container"`` to inherit
                container default.
            dependencies: Explicit dependency mapping from dependency key to
                provider parameter, or ``"infer"`` for annotation inference.
            lock_mode: Lock strategy, or ``"from_container"`` to inherit the
                container lock mode.
            autoregister_dependencies: Override dependency autoregistration for
                this registration.

        Returns:
            ``None`` in direct mode or a decorator in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If parameters are invalid or scope
                contracts cannot be satisfied.
            DIWireInvalidProviderSpecError: If explicit dependencies do not match
                provider signature.
            DIWireProviderDependencyInferenceError: If dependencies cannot be
                inferred from annotations.

        Notes:
            ``lock_mode="from_container"`` inherits the container-level mode.
            Open generic registration is enabled when ``provides`` contains
            TypeVars.

        Examples:
            .. code-block:: python

                container.add_concrete(SqlRepo, provides=Repo)


                @container.add_concrete(provides=Repo)
                class CachedRepo(SqlRepo): ...

        """
        decorator: ConcreteTypeRegistrationDecorator[Any] = ConcreteTypeRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            component=component,
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
        resolved_provides_with_component = self._resolve_registration_component_provides(
            provides=resolved_provides,
            component=component,
            method_name="add_concrete",
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
        registration_provides, has_decoration_chain = self._resolve_registration_target_provides(
            resolved_provides_with_component,
        )

        with self._registration_mutation():
            if (
                self._open_generic_registry.register(
                    provides=registration_provides,
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
                self._finalize_registration_after_binding(
                    original_provides=resolved_provides_with_component,
                    has_decoration_chain=has_decoration_chain,
                )
                return None

            (
                closed_generic_injections,
                dependencies_for_provider,
            ) = self._resolve_closed_concrete_generic_injections(
                provides=resolved_provides_with_component,
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
                        provides=registration_provides,
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
                self._finalize_registration_after_binding(
                    original_provides=resolved_provides_with_component,
                    has_decoration_chain=has_decoration_chain,
                )
                return None

            self._providers_registrations.add(
                ProviderSpec(
                    provides=registration_provides,
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
            self._finalize_registration_after_binding(
                original_provides=resolved_provides_with_component,
                has_decoration_chain=has_decoration_chain,
            )

            return None

    @overload
    def add_factory(
        self,
        factory: Callable[..., Any] | Callable[..., Awaitable[Any]],
        *,
        provides: Any | Literal["infer"] = "infer",
        component: object | None = None,
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
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
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
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | FactoryRegistrationDecorator[Any]:
        """Register a factory provider.

        Supports direct calls and decorator form. ``provides`` may be a protocol,
        concrete type, annotated token, or open generic key. Dependencies are
        inferred from factory parameters unless explicit dependencies are passed.

        Args:
            factory: Provider function/callable, or ``"from_decorator"``.
            provides: Dependency key produced by the factory. ``"infer"`` uses
                the return annotation.
            component: Optional component marker value used to register under
                ``Annotated[provides, Component(...)]``.
            scope: Provider scope, or ``"from_container"``.
            lifetime: Provider lifetime, or ``"from_container"``.
            dependencies: Explicit dependency mapping, or ``"infer"``.
            lock_mode: Lock strategy, or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration for
                this registration.

        Returns:
            ``None`` in direct mode or a decorator in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If configuration or annotations are
                invalid.
            DIWireInvalidProviderSpecError: If explicit dependencies do not match
                factory parameters.
            DIWireProviderDependencyInferenceError: If required dependencies
                cannot be inferred.

        Notes:
            ``lock_mode="from_container"`` inherits the container-level mode.
            Open-generic factories can inject type arguments by accepting
            ``type[T]`` or ``T`` parameters in dependencies.

        Examples:
            .. code-block:: python

                container.add_factory(lambda settings: Client(settings), provides=Client)


                @container.add_factory(provides=Box[T])
                def build_box(value_type: type[T]) -> Box[T]:
                    return Box(value_type)

        """
        decorator: FactoryRegistrationDecorator[Any] = FactoryRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            component=component,
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
        resolved_provides_with_component = self._resolve_registration_component_provides(
            provides=resolved_provides,
            component=component,
            method_name="add_factory",
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
            provides=resolved_provides_with_component,
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
        component: object | None = None,
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
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
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
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | GeneratorRegistrationDecorator[Any]:
        """Register a generator or async-generator provider with cleanup.

        The yielded value is resolved as the dependency, and teardown runs when
        the owning resolver scope exits (or container closes for root scope).

        Args:
            generator: Generator provider, or ``"from_decorator"``.
            provides: Dependency key produced by the yield value.
            component: Optional component marker value used to register under
                ``Annotated[provides, Component(...)]``.
            scope: Provider scope, or ``"from_container"``.
            lifetime: Provider lifetime, or ``"from_container"``.
            dependencies: Explicit dependency mapping, or ``"infer"``.
            lock_mode: Lock strategy, or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration.

        Returns:
            ``None`` in direct mode or a decorator in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If registration arguments are invalid.
            DIWireInvalidProviderSpecError: If explicit dependencies are invalid.
            DIWireProviderDependencyInferenceError: If dependency inference fails.

        Notes:
            Cleanup is deterministic only when the owning resolver is closed
            (`with`/`async with` or explicit close/aclose).

        Examples:
            .. code-block:: python

                @container.add_generator(scope=Scope.REQUEST, provides=Session)
                def open_session(engine: Engine) -> Generator[Session, None, None]:
                    with Session(engine) as session:
                        yield session

        """
        decorator: GeneratorRegistrationDecorator[Any] = GeneratorRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            component=component,
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
        resolved_provides_with_component = self._resolve_registration_component_provides(
            provides=resolved_provides,
            component=component,
            method_name="add_generator",
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
            provides=resolved_provides_with_component,
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
        context_manager: ContextManagerProvider[Any],
        *,
        provides: Any | Literal["infer"] = "infer",
        component: object | None = None,
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
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> ContextManagerRegistrationDecorator[Any]: ...

    def add_context_manager(
        self,
        context_manager: ContextManagerProvider[Any] | Literal["from_decorator"] = "from_decorator",
        *,
        provides: Any | Literal["infer"] = "infer",
        component: object | None = None,
        scope: BaseScope | Literal["from_container"] = "from_container",
        lifetime: Lifetime | Literal["from_container"] = "from_container",
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
        lock_mode: LockMode | Literal["from_container"] = "from_container",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
    ) -> None | ContextManagerRegistrationDecorator[Any]:
        """Register a context-manager or async-context-manager provider.

        The entered value is resolved as the dependency, and ``__exit__`` /
        ``__aexit__`` runs when the owning resolver scope exits.

        Args:
            context_manager: Context-manager provider, or ``"from_decorator"``.
            provides: Dependency key produced by the entered value.
            component: Optional component marker value used to register under
                ``Annotated[provides, Component(...)]``.
            scope: Provider scope, or ``"from_container"``.
            lifetime: Provider lifetime, or ``"from_container"``.
            dependencies: Explicit dependency mapping, or ``"infer"``.
            lock_mode: Lock strategy, or ``"from_container"``.
            autoregister_dependencies: Override dependency autoregistration.

        Returns:
            ``None`` in direct mode or a decorator in decorator mode.

        Raises:
            DIWireInvalidRegistrationError: If registration arguments are invalid.
            DIWireInvalidProviderSpecError: If explicit dependencies are invalid.
            DIWireProviderDependencyInferenceError: If dependency inference fails.

        Notes:
            Cleanup runs at scope/container exit. For request resources, register
            under ``Scope.REQUEST`` and resolve inside a request scope.

        Examples:
            .. code-block:: python

                @container.add_context_manager(scope=Scope.REQUEST, provides=Session)
                def session(engine: Engine) -> ContextManager[Session]:
                    return Session(engine)

        """
        decorator: ContextManagerRegistrationDecorator[Any] = ContextManagerRegistrationDecorator(
            container=self,
            scope=scope,
            lifetime=lifetime,
            provides=provides,
            component=component,
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
        resolved_provides_with_component = self._resolve_registration_component_provides(
            provides=resolved_provides,
            component=component,
            method_name="add_context_manager",
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
            provides=resolved_provides_with_component,
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

    def decorate(
        self,
        *,
        provides: Any,
        component: object | None = None,
        decorator: Callable[..., Any],
        inner_parameter: str | None = None,
    ) -> None:
        """Decorate an existing or future provider binding for a dependency key.

        Decoration rules are persistent for the container lifetime. If a binding
        exists now, decoration is applied immediately. Otherwise the rule is
        stored and applied automatically when the key is registered later.
        """
        if provides is None:
            msg = "decorate() parameter 'provides' must not be None."
            raise DIWireInvalidRegistrationError(msg)
        resolved_provides = self._resolve_registration_component_provides(
            provides=provides,
            component=component,
            method_name="decorate",
        )
        normalized_provides = self._normalize_decoration_provides_key(resolved_provides)

        with self._registration_mutation():
            self._register_decoration_rule(
                provides=normalized_provides,
                decorator=decorator,
                inner_parameter=inner_parameter,
            )
            if self._decoration_chain_by_provides.get(normalized_provides) is not None:
                self._ensure_chain_keys(provides=normalized_provides)
                self._rebuild_decoration_chain(provides=normalized_provides)
                self._invalidate_compilation()
                return
            if self._has_registered_binding(normalized_provides):
                self._apply_pending_decorations(provides=normalized_provides)
                self._invalidate_compilation()

    def _register_decoration_rule(
        self,
        *,
        provides: Any,
        decorator: Callable[..., Any],
        inner_parameter: str | None,
    ) -> None:
        decorator_callable = self._validate_decorator_callable(decorator)
        dependencies = self._extract_decoration_dependencies(
            decorator=decorator_callable,
        )
        resolved_inner_parameter = self._resolve_decoration_inner_parameter(
            provides=provides,
            dependencies=dependencies,
            inner_parameter=inner_parameter,
            decorator=decorator_callable,
        )
        is_async = self._provider_return_type_extractor.is_factory_async(decorator_callable)

        rules = self._decoration_rules_by_provides.setdefault(provides, [])
        rules.append(
            _DecorationRule(
                decorator=decorator_callable,
                inner_parameter=resolved_inner_parameter,
                dependencies=tuple(dependencies),
                is_async=is_async,
            ),
        )

    def _validate_decorator_callable(
        self,
        decorator: Any,
    ) -> Callable[..., Any]:
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

        return cast("Callable[..., Any]", decorator_value)

    def _extract_decoration_dependencies(
        self,
        *,
        decorator: Callable[..., Any],
    ) -> list[ProviderDependency]:
        try:
            return self._provider_dependencies_extractor.extract_from_factory(
                factory=decorator,
            )
        except DIWireError as error:
            msg = (
                "decorate() could not infer dependencies for decorator "
                f"'{self._callable_name(decorator)}': {error}"
            )
            raise DIWireInvalidRegistrationError(msg) from error

    def _resolve_decoration_inner_parameter(
        self,
        *,
        provides: Any,
        dependencies: list[ProviderDependency],
        inner_parameter: str | None,
        decorator: Callable[..., Any],
    ) -> str:
        if inner_parameter is not None:
            if any(dependency.parameter.name == inner_parameter for dependency in dependencies):
                return inner_parameter
            msg = (
                "decorate() parameter 'inner_parameter' must match one of the decorator's "
                "injectable parameters."
            )
            raise DIWireInvalidRegistrationError(msg)

        matched_parameter_names = [
            dependency.parameter.name
            for dependency in dependencies
            if dependency.provides == provides
        ]
        if len(matched_parameter_names) == 1:
            return matched_parameter_names[0]
        if not matched_parameter_names:
            msg = (
                "decorate() could not infer the inner parameter for decorator "
                f"'{self._callable_name(decorator)}' and provides {provides!r}. "
                "Pass inner_parameter='...'."
            )
            raise DIWireInvalidRegistrationError(msg)

        msg = (
            "decorate() found multiple inner parameter candidates for decorator "
            f"'{self._callable_name(decorator)}' and provides {provides!r}. "
            "Pass inner_parameter='...'."
        )
        raise DIWireInvalidRegistrationError(msg)

    def _finalize_registration_after_binding(
        self,
        *,
        original_provides: Any,
        has_decoration_chain: bool,
    ) -> None:
        normalized_provides = self._normalize_decoration_provides_key(original_provides)
        if has_decoration_chain:
            self._rebuild_decoration_chain(provides=normalized_provides)
        elif self._decoration_rules_by_provides.get(normalized_provides):
            self._apply_pending_decorations(provides=normalized_provides)
        self._invalidate_compilation()

    def _resolve_registration_target_provides(self, provides: Any) -> tuple[Any, bool]:
        normalized_provides = self._normalize_decoration_provides_key(provides)
        chain = self._decoration_chain_by_provides.get(normalized_provides)
        if chain is None:
            return provides, False
        return chain.base_key, True

    def _apply_pending_decorations(self, *, provides: Any) -> None:
        rules = self._decoration_rules_by_provides.get(provides)
        if not rules:
            return
        if not self._has_registered_binding(provides):
            return

        rule_count = len(rules)
        chain = self._build_decoration_chain(
            provides=provides,
            rule_count=rule_count,
        )
        self._move_current_binding_to_base_key(
            provides=provides,
            base_key=chain.base_key,
        )
        self._rebuild_decoration_chain(
            provides=provides,
            chain=chain,
        )
        self._decoration_chain_by_provides[provides] = chain

    def _ensure_chain_keys(self, *, provides: Any) -> None:
        chain = self._decoration_chain_by_provides.get(provides)
        if chain is None:
            return
        rules = self._decoration_rules_by_provides.get(provides, [])
        expected_layers = len(rules)
        if expected_layers == len(chain.layer_keys):
            return
        if expected_layers < len(chain.layer_keys):
            msg = f"Decoration chain for {provides!r} has more layers than rules."
            raise DIWireInvalidRegistrationError(msg)
        while len(chain.layer_keys) < expected_layers:
            insertion_index = max(len(chain.layer_keys) - 1, 0)
            chain.layer_keys.insert(
                insertion_index,
                self._create_decoration_alias_key(
                    provides=provides,
                    layer=insertion_index,
                ),
            )

    def _build_decoration_chain(
        self,
        *,
        provides: Any,
        rule_count: int,
    ) -> _DecorationChain:
        base_key = self._create_decoration_alias_key(
            provides=provides,
            layer=-1,
        )
        layer_keys: list[Any] = [provides]
        if rule_count > 1:
            layer_keys = [
                self._create_decoration_alias_key(
                    provides=provides,
                    layer=layer,
                )
                for layer in range(rule_count - 1)
            ]
            layer_keys.append(provides)
        return _DecorationChain(
            base_key=base_key,
            layer_keys=layer_keys,
        )

    def _move_current_binding_to_base_key(
        self,
        *,
        provides: Any,
        base_key: Any,
    ) -> None:
        if self._is_open_generic_provides(provides):
            open_spec = self._open_generic_registry.find_exact(provides)
            if open_spec is None:
                msg = f"Cannot decorate {provides!r}: base open-generic binding is not registered."
                raise DIWireInvalidRegistrationError(msg)
            dependencies = [binding.dependency for binding in open_spec.bindings]
            self._open_generic_registry.register(
                provides=base_key,
                provider_kind=open_spec.provider_kind,
                provider=open_spec.provider,
                lifetime=open_spec.lifetime,
                scope=open_spec.scope,
                lock_mode=open_spec.lock_mode,
                is_async=open_spec.is_async,
                is_any_dependency_async=open_spec.is_any_dependency_async,
                needs_cleanup=open_spec.needs_cleanup,
                dependencies=dependencies,
            )
            return

        provider_spec = self._providers_registrations.find_by_type(provides)
        if provider_spec is None:
            msg = f"Cannot decorate {provides!r}: base binding is not registered."
            raise DIWireInvalidRegistrationError(msg)

        self._providers_registrations.add(
            self._copy_provider_spec_with_new_key(
                provider_spec=provider_spec,
                provides=base_key,
            ),
        )

    def _copy_provider_spec_with_new_key(
        self,
        *,
        provider_spec: ProviderSpec,
        provides: Any,
    ) -> ProviderSpec:
        return ProviderSpec(
            provides=provides,
            instance=provider_spec.instance,
            concrete_type=provider_spec.concrete_type,
            factory=provider_spec.factory,
            generator=provider_spec.generator,
            context_manager=provider_spec.context_manager,
            dependencies=list(provider_spec.dependencies),
            is_async=provider_spec.is_async,
            is_any_dependency_async=provider_spec.is_any_dependency_async,
            needs_cleanup=provider_spec.needs_cleanup,
            lock_mode=provider_spec.lock_mode,
            lifetime=provider_spec.lifetime,
            scope=provider_spec.scope,
        )

    def _rebuild_decoration_chain(
        self,
        *,
        provides: Any,
        chain: _DecorationChain | None = None,
    ) -> None:
        active_chain = (
            chain if chain is not None else self._decoration_chain_by_provides.get(provides)
        )
        if active_chain is None:
            return
        rules = self._decoration_rules_by_provides.get(provides)
        if not rules:
            return
        if len(active_chain.layer_keys) != len(rules):
            msg = f"Decoration chain for {provides!r} is out of sync with rules."
            raise DIWireInvalidRegistrationError(msg)

        base_metadata = self._resolve_decoration_base_metadata(
            provides=provides,
            base_key=active_chain.base_key,
        )
        inner_key = active_chain.base_key

        for index, rule in enumerate(rules):
            out_key = active_chain.layer_keys[index]
            dependencies = self._build_decorator_dependencies(
                rule=rule,
                inner_key=inner_key,
            )
            is_any_dependency_async = self._provider_return_type_extractor.is_any_dependency_async(
                dependencies,
            )

            if base_metadata.is_open_generic:
                self._register_open_generic_decorator_layer(
                    provides=out_key,
                    rule=rule,
                    dependencies=dependencies,
                    metadata=base_metadata,
                    is_any_dependency_async=is_any_dependency_async,
                )
            else:
                self._providers_registrations.add(
                    ProviderSpec(
                        provides=out_key,
                        factory=rule.decorator,
                        lifetime=base_metadata.lifetime,
                        scope=base_metadata.scope,
                        dependencies=dependencies,
                        is_async=rule.is_async,
                        is_any_dependency_async=is_any_dependency_async,
                        needs_cleanup=False,
                        lock_mode=base_metadata.lock_mode,
                    ),
                )

            self._autoregister_provider_dependencies(
                dependencies=dependencies,
                scope=base_metadata.scope,
                lifetime=base_metadata.lifetime,
                enabled=self._resolve_autoregister_dependencies(None),
            )
            inner_key = out_key

    def _build_decorator_dependencies(
        self,
        *,
        rule: _DecorationRule,
        inner_key: Any,
    ) -> list[ProviderDependency]:
        resolved_dependencies: list[ProviderDependency] = []
        inner_resolved = False
        for dependency in rule.dependencies:
            if dependency.parameter.name == rule.inner_parameter:
                resolved_dependencies.append(
                    ProviderDependency(
                        provides=inner_key,
                        parameter=dependency.parameter,
                    ),
                )
                inner_resolved = True
            else:
                resolved_dependencies.append(dependency)
        if inner_resolved:
            return resolved_dependencies
        msg = (
            "decorate() configured an unknown inner parameter "
            f"'{rule.inner_parameter}' for decorator '{self._callable_name(rule.decorator)}'."
        )
        raise DIWireInvalidRegistrationError(msg)

    def _register_open_generic_decorator_layer(
        self,
        *,
        provides: Any,
        rule: _DecorationRule,
        dependencies: list[ProviderDependency],
        metadata: _DecorationBaseMetadata,
        is_any_dependency_async: bool,
    ) -> None:
        registered_spec = self._open_generic_registry.register(
            provides=provides,
            provider_kind="factory",
            provider=rule.decorator,
            lifetime=metadata.lifetime,
            scope=metadata.scope,
            lock_mode=metadata.lock_mode,
            is_async=rule.is_async,
            is_any_dependency_async=is_any_dependency_async,
            needs_cleanup=False,
            dependencies=dependencies,
        )
        if registered_spec is None:
            msg = f"Cannot register open-generic decorator layer for key {provides!r}."
            raise DIWireInvalidRegistrationError(msg)

    def _resolve_decoration_base_metadata(
        self,
        *,
        provides: Any,
        base_key: Any,
    ) -> _DecorationBaseMetadata:
        if self._is_open_generic_provides(provides):
            open_spec = self._open_generic_registry.find_exact(base_key)
            if open_spec is None:
                msg = f"Decoration base binding for {provides!r} is missing."
                raise DIWireInvalidRegistrationError(msg)
            return _DecorationBaseMetadata(
                lifetime=open_spec.lifetime,
                scope=open_spec.scope,
                lock_mode=open_spec.lock_mode,
                is_open_generic=True,
            )

        provider_spec = self._providers_registrations.find_by_type(base_key)
        if provider_spec is None:
            msg = f"Decoration base binding for {provides!r} is missing."
            raise DIWireInvalidRegistrationError(msg)
        if provider_spec.lifetime is None:
            msg = f"Decoration base binding for {provides!r} has no lifetime."
            raise DIWireInvalidRegistrationError(msg)
        return _DecorationBaseMetadata(
            lifetime=provider_spec.lifetime,
            scope=provider_spec.scope,
            lock_mode=provider_spec.lock_mode,
            is_open_generic=False,
        )

    def _has_registered_binding(self, provides: Any) -> bool:
        if self._is_open_generic_provides(provides):
            return self._open_generic_registry.find_exact(provides) is not None
        return self._providers_registrations.find_by_type(provides) is not None

    def _normalize_decoration_provides_key(self, provides: Any) -> Any:
        canonical_open_key = canonicalize_open_key(provides)
        if canonical_open_key is None:
            return provides
        return canonical_open_key

    def _create_decoration_alias_key(
        self,
        *,
        provides: Any,
        layer: int,
    ) -> Any:
        self._decoration_counter += 1
        alias_id = self._decoration_counter
        if self._is_open_generic_provides(provides):
            return Annotated[provides, _OpenDecorationAlias(id=alias_id, layer=layer)]
        return type(f"_DIWireInner_{alias_id}", (), {})

    def _is_open_generic_provides(self, provides: Any) -> bool:
        return canonicalize_open_key(provides) is not None

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

    def _resolve_registration_component_provides(
        self,
        *,
        provides: Any,
        component: object | None,
        method_name: str,
    ) -> Any:
        if component is None:
            return provides
        if component_base_key(provides) is not None:
            msg = (
                f"{method_name}() received both a component-qualified 'provides' key "
                f"({provides!r}) and 'component'. Omit component=... or pass the non-component "
                "base key in provides=... and keep component=...."
            )
            raise DIWireInvalidRegistrationError(msg)

        component_marker = self._normalize_registration_component(component=component)
        if get_origin(provides) is not Annotated:
            return build_annotated_key((provides, component_marker))

        annotation_args = get_args(provides)
        provides_inner = annotation_args[0]
        metadata = annotation_args[1:]
        return build_annotated_key((provides_inner, *metadata, component_marker))

    def _normalize_registration_component(self, *, component: object) -> Component:
        if isinstance(component, Component):
            return component
        return Component(component)

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
        dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"],
        method_name: str,
    ) -> list[ProviderDependency] | None:
        dependencies_value = cast("Any", dependencies)
        if dependencies_value == "infer":
            return None
        if not isinstance(dependencies_value, Mapping):
            msg = (
                f"{method_name}() parameter 'dependencies' must be a "
                "mapping[Any, inspect.Parameter] or 'infer'."
            )
            raise DIWireInvalidRegistrationError(msg)

        resolved_dependencies: list[ProviderDependency] = []
        for provides_key, parameter in dependencies_value.items():
            if not isinstance(parameter, inspect.Parameter):
                msg = (
                    f"{method_name}() parameter 'dependencies' must be a "
                    "mapping[Any, inspect.Parameter] or 'infer'."
                )
                raise DIWireInvalidRegistrationError(msg)
            resolved_dependencies.append(
                ProviderDependency(
                    provides=provides_key,
                    parameter=parameter,
                ),
            )

        return resolved_dependencies

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
        registration_provides, has_decoration_chain = self._resolve_registration_target_provides(
            provides,
        )

        with self._registration_mutation():
            if (
                self._open_generic_registry.register(
                    provides=registration_provides,
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
                self._finalize_registration_after_binding(
                    original_provides=provides,
                    has_decoration_chain=has_decoration_chain,
                )
                return

            if provider_field == "factory":
                provider_spec = ProviderSpec(
                    provides=registration_provides,
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
                    provides=registration_provides,
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
                    provides=registration_provides,
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
            self._finalize_registration_after_binding(
                original_provides=provides,
                has_decoration_chain=has_decoration_chain,
            )
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
        normalized_provides = provides
        if get_origin(normalized_provides) is Annotated:
            normalized_provides = get_args(normalized_provides)[0]

        origin = get_origin(normalized_provides)
        if origin is None:
            return {}

        arguments = get_args(normalized_provides)
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
            dependency_key = self._unwrap_provider_dependency_key(dependency.provides)
            if self._providers_registrations.find_by_type(dependency_key):
                continue
            with suppress(DIWireError):
                self._autoregister_dependency(
                    dependency=dependency_key,
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
        dependency_key = self._unwrap_provider_dependency_key(dependency)

        if self._providers_registrations.find_by_type(dependency_key):
            return
        if self._open_generic_registry.has_match_for_dependency(dependency_key):
            return

        self._autoregister_dependency(
            dependency=dependency_key,
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
        """Decorate a callable to resolve ``Injected`` and ``FromContext`` parameters.

        The wrapper hides injected/context parameters from the public signature.
        Callers may still override any injected argument explicitly.

        Args:
            func: Callable to wrap, or ``"from_decorator"`` for decorator form.
            scope: Explicit scope to open for each call, or ``"infer"`` to infer
                required depth from injected dependency scopes.
            autoregister_dependencies: Override dependency autoregistration for
                injected keys.
            auto_open_scope: Open inferred/explicit scope automatically.

        Returns:
            Wrapped callable, or a decorator when ``func="from_decorator"``.

        Raises:
            DIWireInvalidRegistrationError: If arguments are invalid, reserved
                parameter names are declared, or context usage is inconsistent.

        Notes:
            Reserved kwargs consumed by wrappers:
            ``__diwire_context`` and ``__diwire_resolver``.
            Wrapped callables cannot declare parameters with those names.

        Examples:
            .. code-block:: python

                @container.inject(scope=Scope.REQUEST)
                def handle(
                    service: Injected[Service],
                    tenant_id: FromContext[int],
                    value: int,
                ) -> str:
                    return service.process(value, tenant_id)


                result = handle(10, __diwire_context={int: 7})

        """
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
            dependency_key = self._unwrap_provider_dependency_key(injected_parameter.dependency)
            if self._providers_registrations.find_by_type(dependency_key):
                continue
            with suppress(DIWireError):
                self._autoregister_dependency(
                    dependency=dependency_key,
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
        if is_maybe_annotation(dependency):
            maybe_inner_dependency = strip_maybe_annotation(dependency)
            inferred_level = self._infer_dependency_scope_level(
                dependency=maybe_inner_dependency,
                cache=cache,
                in_progress=in_progress,
            )
            cache[dependency] = inferred_level
            return inferred_level
        if is_provider_annotation(dependency):
            provider_inner_dependency = strip_provider_annotation(dependency)
            inferred_level = self._infer_dependency_scope_level(
                dependency=provider_inner_dependency,
                cache=cache,
                in_progress=in_progress,
            )
            cache[dependency] = inferred_level
            return inferred_level
        if is_all_annotation(dependency):
            if dependency in in_progress:
                return self._root_scope.level

            inner = strip_all_annotation(dependency)
            collected_keys: list[Any] = []
            if self._providers_registrations.find_by_type(inner) is not None:
                collected_keys.append(inner)
            collected_keys.extend(
                spec.provides
                for spec in self._providers_registrations.values()
                if component_base_key(spec.provides) == inner
            )
            if not collected_keys:
                cache[dependency] = self._root_scope.level
                return self._root_scope.level

            in_progress.add(dependency)
            try:
                inferred_level = max(
                    self._infer_dependency_scope_level(
                        dependency=collected_key,
                        cache=cache,
                        in_progress=in_progress,
                    )
                    for collected_key in collected_keys
                )
            finally:
                in_progress.remove(dependency)
            cache[dependency] = inferred_level
            return inferred_level

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

    def _unwrap_provider_dependency_key(self, dependency: Any) -> Any:
        provider_inner_dependency = self._extract_provider_inner_dependency_fast(dependency)
        if provider_inner_dependency is None:
            return dependency
        return provider_inner_dependency

    def _extract_provider_inner_dependency_fast(self, dependency: Any) -> Any | None:
        metadata = getattr(dependency, "__metadata__", None)
        if metadata is None:
            return None
        for marker in metadata:
            if isinstance(marker, ProviderMarker):
                return marker.dependency_key
        return None

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
            dependency = injected_parameter.dependency
            if is_maybe_annotation(dependency):
                inner_dependency = strip_maybe_annotation(dependency)
                if is_provider_annotation(inner_dependency) or is_from_context_annotation(
                    inner_dependency,
                ):
                    bound_arguments.arguments[injected_parameter.name] = resolver.resolve(
                        dependency,
                    )
                    continue
                if not self._is_registered_in_resolver(
                    resolver=resolver,
                    dependency=inner_dependency,
                ):
                    parameter = signature.parameters[injected_parameter.name]
                    if parameter.default is inspect.Parameter.empty:
                        bound_arguments.arguments[injected_parameter.name] = None
                    continue
                bound_arguments.arguments[injected_parameter.name] = resolver.resolve(
                    inner_dependency,
                )
                continue
            bound_arguments.arguments[injected_parameter.name] = resolver.resolve(dependency)
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
            dependency = injected_parameter.dependency
            if is_maybe_annotation(dependency):
                inner_dependency = strip_maybe_annotation(dependency)
                if is_provider_annotation(inner_dependency) or is_from_context_annotation(
                    inner_dependency,
                ):
                    bound_arguments.arguments[injected_parameter.name] = await resolver.aresolve(
                        dependency,
                    )
                    continue
                if not self._is_registered_in_resolver(
                    resolver=resolver,
                    dependency=inner_dependency,
                ):
                    parameter = signature.parameters[injected_parameter.name]
                    if parameter.default is inspect.Parameter.empty:
                        bound_arguments.arguments[injected_parameter.name] = None
                    continue
                bound_arguments.arguments[injected_parameter.name] = await resolver.aresolve(
                    inner_dependency,
                )
                continue
            bound_arguments.arguments[injected_parameter.name] = await resolver.aresolve(
                dependency,
            )
        for context_parameter in context_parameters:
            if context_parameter.name in bound_arguments.arguments:
                continue
            bound_arguments.arguments[context_parameter.name] = await resolver.aresolve(
                context_parameter.dependency,
            )
        return bound_arguments

    def _is_registered_in_resolver(
        self,
        *,
        resolver: ResolverProtocol,
        dependency: Any,
    ) -> bool:
        is_registered_dependency = getattr(resolver, "_is_registered_dependency", None)
        if callable(is_registered_dependency):
            return bool(is_registered_dependency(dependency))
        if self._providers_registrations.find_by_type(dependency) is not None:
            return True
        return self._open_generic_registry.find_best_match(dependency) is not None

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

        Compilation is lazy and invalidated by any registration mutation. In
        strict mode (autoregistration disabled), hot-path entrypoints are
        rebound to the compiled resolver for lower call overhead.

        Returns:
            The compiled root resolver.

        Notes:
            Call this once after startup registrations when you want stable
            strict-mode hot-path behavior. Any registration mutation invalidates
            the compiled graph automatically.

        Examples:
            .. code-block:: python

                container.add_concrete(Service)
                container.compile()
                service = container.resolve(Service)

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
                decoration_rules_by_provides={
                    provides: list(rules)
                    for provides, rules in self._decoration_rules_by_provides.items()
                },
                decoration_chain_by_provides={
                    provides: _DecorationChain(
                        base_key=chain.base_key,
                        layer_keys=list(chain.layer_keys),
                    )
                    for provides, chain in self._decoration_chain_by_provides.items()
                },
                decoration_counter=self._decoration_counter,
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
                    self._decoration_rules_by_provides = {
                        provides: list(rules)
                        for provides, rules in snapshot.decoration_rules_by_provides.items()
                    }
                    self._decoration_chain_by_provides = {
                        provides: _DecorationChain(
                            base_key=chain.base_key,
                            layer_keys=list(chain.layer_keys),
                        )
                        for provides, chain in snapshot.decoration_chain_by_provides.items()
                    }
                    self._decoration_counter = snapshot.decoration_counter
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
        """Resolve a dependency synchronously.

        Args:
            dependency: Dependency key to resolve.

        Returns:
            Resolved dependency value.

        Raises:
            DIWireDependencyNotRegisteredError: If dependency is missing in
                strict mode and no open-generic match exists.
            DIWireScopeMismatchError: If dependency requires a deeper scope than
                the current resolver.
            DIWireAsyncDependencyInSyncContextError: If the selected graph
                requires async resolution or cleanup.
            DIWireInvalidGenericTypeArgumentError: If closed generic arguments
                violate TypeVar constraints.

        Notes:
            Typical fixes:
            1. Register missing dependencies (or enable autoregistration).
            2. Enter required scope before resolving scoped dependencies.
            3. Switch to ``aresolve`` for async dependency chains.
            4. Use compatible generic arguments for constrained TypeVars.

        Examples:
            .. code-block:: python

                container.add_concrete(Service)
                service = container.resolve(Service)

        """
        resolver = self._root_resolver
        if resolver is None:
            resolver = self.compile()

        if not self._autoregister_concrete_types:
            return resolver.resolve(dependency)

        provider_inner_dependency = self._extract_provider_inner_dependency_fast(dependency)
        if provider_inner_dependency is not None:
            graph_revision_before = self._graph_revision
            self._ensure_autoregistration(provider_inner_dependency)
            if self._graph_revision != graph_revision_before:
                resolver = self.compile()
            return resolver.resolve(dependency)

        try:
            return resolver.resolve(dependency)
        except DIWireDependencyNotRegisteredError:
            graph_revision_before = self._graph_revision
            self._ensure_autoregistration(dependency)
            if self._graph_revision == graph_revision_before:
                raise
            resolver = self.compile()
            return resolver.resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        """Resolve a dependency asynchronously.

        Args:
            dependency: Dependency key to resolve.

        Returns:
            Resolved dependency value.

        Raises:
            DIWireDependencyNotRegisteredError: If dependency is missing in
                strict mode and no open-generic match exists.
            DIWireScopeMismatchError: If dependency requires a deeper scope than
                the current resolver.
            DIWireInvalidGenericTypeArgumentError: If closed generic arguments
                violate TypeVar constraints.

        Notes:
            Use this API whenever any part of the selected provider chain is
            async.

        Examples:
            .. code-block:: python

                container.add_factory(async_make_client, provides=Client)
                client = await container.aresolve(Client)

        """
        resolver = self._root_resolver
        if resolver is None:
            resolver = self.compile()

        if not self._autoregister_concrete_types:
            return await resolver.aresolve(dependency)

        provider_inner_dependency = self._extract_provider_inner_dependency_fast(dependency)
        if provider_inner_dependency is not None:
            graph_revision_before = self._graph_revision
            self._ensure_autoregistration(provider_inner_dependency)
            if self._graph_revision != graph_revision_before:
                resolver = self.compile()
            return await resolver.aresolve(dependency)

        try:
            return await resolver.aresolve(dependency)
        except DIWireDependencyNotRegisteredError:
            graph_revision_before = self._graph_revision
            self._ensure_autoregistration(dependency)
            if self._graph_revision == graph_revision_before:
                raise
            resolver = self.compile()
            return await resolver.aresolve(dependency)

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
        """Enter a deeper scope and return a scoped resolver.

        When ``scope`` is ``None``, DIWire transitions to the next deeper
        non-skippable scope. Context keys are used by ``FromContext[...]``
        lookups and inherited by deeper nested scopes unless overridden.

        Args:
            scope: Explicit target scope, or ``None`` for default next scope.
            context: Optional mapping for ``FromContext[...]`` dependencies.

        Returns:
            Resolver bound to the target scope.

        Raises:
            DIWireScopeMismatchError: If transition is invalid for the current
                scope level.

        Examples:
            .. code-block:: python

                with container.enter_scope(
                    Scope.REQUEST,
                    context={int: 1001},
                ) as request_resolver:
                    user_id = request_resolver.resolve(FromContext[int])

        """
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
        """Close the root resolver and run pending cleanup callbacks.

        Args:
            exc_type: Optional exception type propagated to cleanup callbacks.
            exc_value: Optional exception instance propagated to callbacks.
            traceback: Optional traceback propagated to callbacks.

        Raises:
            RuntimeError: If called before entering/compiling a resolver context.

        Notes:
            Cleanup runs only for graphs that created cleanup-enabled resources.
            Prefer ``with container.enter_scope(...)`` for deterministic request
            cleanup.

        """
        return self.__exit__(exc_type, exc_value, traceback)

    async def aclose(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Asynchronously close the root resolver and run cleanup callbacks.

        Args:
            exc_type: Optional exception type propagated to cleanup callbacks.
            exc_value: Optional exception instance propagated to callbacks.
            traceback: Optional traceback propagated to callbacks.

        Raises:
            RuntimeError: If called before entering/compiling a resolver context.

        Notes:
            Prefer ``async with`` for scoped async workloads; use this when
            owning a long-lived root resolver lifecycle explicitly.

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
    component: object | None = None
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, concrete_type: C) -> C:
        """Register the concrete type provider in the container."""
        self.container.add_concrete(
            concrete_type,
            provides=self.provides,
            component=self.component,
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
    component: object | None = None
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, factory: F) -> F:
        """Register the factory provider in the container."""
        self.container.add_factory(
            factory,
            provides=self.provides,
            component=self.component,
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
    component: object | None = None
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, generator: F) -> F:
        """Register the generator provider in the container."""
        self.container.add_generator(
            generator,
            provides=self.provides,
            component=self.component,
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
    component: object | None = None
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer"
    lock_mode: LockMode | Literal["from_container"] = "from_container"
    autoregister_dependencies: bool | Literal["from_container"] = "from_container"

    def __call__(self, context_manager: F) -> F:
        """Register the context manager provider in the container."""
        self.container.add_context_manager(
            context_manager,
            provides=self.provides,
            component=self.component,
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
class _DecorationRule:
    decorator: Callable[..., Any]
    inner_parameter: str
    dependencies: tuple[ProviderDependency, ...]
    is_async: bool


@dataclass(slots=True)
class _DecorationChain:
    base_key: Any
    layer_keys: list[Any]


@dataclass(frozen=True, slots=True)
class _OpenDecorationAlias:
    id: int
    layer: int


@dataclass(frozen=True, slots=True)
class _DecorationBaseMetadata:
    lifetime: Lifetime
    scope: BaseScope
    lock_mode: LockMode | Literal["auto"]
    is_open_generic: bool


@dataclass(frozen=True, slots=True)
class _ContainerGraphSnapshot:
    providers_registrations: ProvidersRegistrations.Snapshot
    open_generic_registry: OpenGenericRegistry.Snapshot
    decoration_rules_by_provides: dict[Any, list[_DecorationRule]]
    decoration_chain_by_provides: dict[Any, _DecorationChain]
    decoration_counter: int
