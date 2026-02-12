from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum, auto
from inspect import Parameter
from types import TracebackType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Protocol,
    TypeAlias,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from diwire._internal.lock_mode import LockMode
from diwire._internal.scope import BaseScope
from diwire.exceptions import (
    DIWireInvalidProviderSpecError,
    DIWireInvalidRegistrationError,
    DIWireProviderDependencyInferenceError,
)

T = TypeVar("T")
_CMT_co = TypeVar("_CMT_co", covariant=True)

UserDependency: TypeAlias = Any
"""A dependency that been registered or trying to be resolved from the user's code."""

UserProviderObject: TypeAlias = Any
"""An object, function, or class provided by the user as a provider. Determined by ProviderKind."""

ProviderSlot: TypeAlias = int
"""A unique slot number assigned to each provider specification."""

ConcreteTypeProvider: TypeAlias = type[T]
"""A concrete type that can be instantiated to produce a dependency."""

FactoryProvider: TypeAlias = Callable[..., T] | Callable[..., Awaitable[T]]
"""A factory function or asynchronous function that produces a dependency."""

GeneratorProvider: TypeAlias = (
    Callable[..., Generator[T, None, None]] | Callable[..., AsyncGenerator[T, None]]
)
"""A generator function or asynchronous generator function that yields a dependency."""


class _ContextManagerLike(Protocol[_CMT_co]):
    def __enter__(self) -> _CMT_co: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class _AsyncContextManagerLike(Protocol[_CMT_co]):
    def __aenter__(self) -> Awaitable[_CMT_co]: ...

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[bool | None]: ...


ContextManagerProvider: TypeAlias = (
    Callable[..., _ContextManagerLike[T]] | Callable[..., _AsyncContextManagerLike[T]]
)

_MISSING_ANNOTATION: Any = object()
_IMPLICIT_FIRST_PARAMETER_NAMES = {"self", "cls"}
_COROUTINE_RESULT_INDEX = 2
_COROUTINE_ARGUMENT_COUNT = 3
_ASYNC_RESOLVER_ORIGINS: tuple[type[Any], ...] = (
    Awaitable,
    Coroutine,
    AsyncGenerator,
    AbstractAsyncContextManager,
)


@dataclass(kw_only=True)
class ProviderSpec:
    """Describe how a single dependency key is produced and cached.

    A spec is the normalized registration model used by resolver generation.
    Exactly one provider source is expected in user-facing registrations
    (instance, concrete type, factory, generator, or context manager), plus
    metadata describing scope, lifetime, async requirements, cleanup behavior,
    and locking.
    """

    SLOT_COUNTER: ClassVar[ProviderSlot] = 0

    provides: UserDependency
    """The dependency type that this provider supplies."""

    instance: UserDependency | None = None
    """An optional instance of the provided dependency, if applicable."""
    concrete_type: ConcreteTypeProvider[Any] | None = None
    """An optional concrete type of the provided dependency, if applicable."""
    factory: FactoryProvider[Any] | None = None
    """An optional factory function to create the provided dependency, if applicable."""
    generator: GeneratorProvider[Any] | None = None
    """An optional generator function to yield the provided dependency, if applicable."""
    context_manager: ContextManagerProvider[Any] | None = None
    """An optional context manager function to manage the provided dependency, if applicable."""
    dependencies: list[ProviderDependency] = field(default_factory=list)
    """A list of dependencies required by this provider."""
    is_async: bool
    """Indicates whether the provider specification itself is asynchronous."""
    is_any_dependency_async: bool
    """Indicates whether any dependency requires asynchronous resolution."""
    needs_cleanup: bool
    """True if provider itself or any dependency requires cleanup."""
    lock_mode: LockMode | Literal["auto"] = "auto"
    """Resolved locking strategy for this provider."""

    lifetime: Lifetime | None = None
    """The lifetime of the provided dependency. Could be none in case of instance providers."""
    scope: BaseScope
    """The scope in which the provided dependency is valid."""

    slot: ProviderSlot = field(init=False)
    """A unique slot number assigned to this provider specification."""

    def __post_init__(self) -> None:
        self.__class__.SLOT_COUNTER += 1
        self.slot = self.SLOT_COUNTER


class Lifetime(Enum):
    """Define cache behavior for provider results."""

    TRANSIENT = auto()
    """Disable caching and build a new value for every resolution call."""

    SCOPED = auto()
    """Cache per declared scope owner until that scope exits.

    For registrations declared on the container root scope, this behaves like a
    singleton for the container lifetime. Cleanup-enabled providers are released
    when the owning scope/resolver is closed.
    """


class ProvidersRegistrations:
    """Store provider specs indexed by dependency key and slot.

    Registration keys are unique: adding a spec for an existing dependency key
    replaces the previous spec. Slot indexing is maintained for resolver
    planning, and cleanup flags are recomputed after each mutation.
    """

    def __init__(self) -> None:
        self._registrations_by_type: dict[UserDependency, ProviderSpec] = {}
        self._registrations_by_slot: dict[int, ProviderSpec] = {}

    @dataclass(frozen=True, slots=True)
    class Snapshot:
        """Capture provider registration state for transactional rollback."""

        registrations_by_type: dict[UserDependency, ProviderSpec]
        registrations_by_slot: dict[int, ProviderSpec]

    def snapshot(self) -> Snapshot:
        """Capture current registrations for rollback."""
        return self.Snapshot(
            registrations_by_type=dict(self._registrations_by_type),
            registrations_by_slot=dict(self._registrations_by_slot),
        )

    def restore(self, snapshot: Snapshot) -> None:
        """Restore registrations from a previous snapshot.

        Args:
            snapshot: Previously captured snapshot state to restore into the registry.

        """
        self._registrations_by_type = dict(snapshot.registrations_by_type)
        self._registrations_by_slot = dict(snapshot.registrations_by_slot)
        self._refresh_needs_cleanup_flags()

    def add(self, spec: ProviderSpec) -> None:
        """Add a new provider specification to the registrations.

        Args:
            spec: Provider specification to register.

        """
        if previous_spec := self._registrations_by_type.get(spec.provides):
            self._registrations_by_slot.pop(previous_spec.slot, None)
        self._registrations_by_type[spec.provides] = spec
        self._registrations_by_slot[spec.slot] = spec
        self._refresh_needs_cleanup_flags()

    def get_by_type(self, dep_type: UserDependency) -> ProviderSpec:
        """Get a provider specification by the type of dependency it provides.

        Args:
            dep_type: Dependency type key to look up.

        """
        return self._registrations_by_type[dep_type]

    def find_by_type(self, dep_type: UserDependency) -> ProviderSpec | None:
        """Get a provider specification by dependency type, if it exists.

        Args:
            dep_type: Dependency type key to look up.

        """
        return self._registrations_by_type.get(dep_type)

    def get_by_slot(self, slot: int) -> ProviderSpec:
        """Get a provider specification by its unique slot number.

        Args:
            slot: Provider slot identifier to look up.

        """
        return self._registrations_by_slot[slot]

    def get_by_scope(self, scope: BaseScope | None) -> list[ProviderSpec]:
        """Get all provider specifications registered for a specific scope.

        Args:
            scope: Scope value used to filter registrations or open nested resolution scope.

        """
        return [spec for spec in self._registrations_by_type.values() if spec.scope == scope]

    def values(self) -> list[ProviderSpec]:
        """Get all provider specifications."""
        return list(self._registrations_by_type.values())

    def _refresh_needs_cleanup_flags(self) -> None:
        """Recompute cleanup requirements for all registered providers."""
        # Dependencies can be registered after dependents, so recompute until stable.
        has_changes = True
        while has_changes:
            has_changes = False
            for spec in self.values():
                dependency_needs_cleanup = any(
                    dependency_spec.needs_cleanup
                    for dependency in spec.dependencies
                    if (dependency_spec := self.find_by_type(dependency.provides))
                )
                needs_cleanup = (
                    spec.generator is not None
                    or spec.context_manager is not None
                    or dependency_needs_cleanup
                )
                if spec.needs_cleanup is not needs_cleanup:
                    spec.needs_cleanup = needs_cleanup
                    has_changes = True

    def __len__(self) -> int:
        return len(self._registrations_by_type)


@dataclass(slots=True)
class ProviderDependenciesExtractor:
    """Extracts dependencies from user-defined provider objects."""

    def extract_from_concrete_type(
        self,
        concrete_type: ConcreteTypeProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a concrete type-based provider.

        Args:
            concrete_type: Concrete class provider to inspect or validate.

        """
        return self._extract_dependencies(
            provider=concrete_type,
            provider_name=concrete_type.__qualname__,
            skip_first_parameter=False,
        )

    def extract_from_factory(
        self,
        factory: FactoryProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a factory-based provider.

        Args:
            factory: Factory provider callable to inspect or validate.

        """
        return self._extract_dependencies(
            provider=factory,
            provider_name=self._provider_name(factory),
            skip_first_parameter=False,
        )

    def extract_from_generator(
        self,
        generator: GeneratorProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a generator-based provider.

        Args:
            generator: Generator provider callable to inspect or validate.

        """
        return self._extract_dependencies(
            provider=generator,
            provider_name=self._provider_name(generator),
            skip_first_parameter=False,
        )

    def extract_from_context_manager(
        self,
        context_manager: ContextManagerProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a context manager-based provider.

        Args:
            context_manager: Context manager provider callable to inspect or validate.

        """
        return self._extract_dependencies(
            provider=context_manager,
            provider_name=self._provider_name(context_manager),
            skip_first_parameter=False,
        )

    def validate_explicit_for_concrete_type(
        self,
        concrete_type: ConcreteTypeProvider[Any],
        dependencies: list[ProviderDependency],
    ) -> list[ProviderDependency]:
        """Validate explicit dependencies for a concrete type-based provider.

        Args:
            concrete_type: Concrete class provider to inspect or validate.
            dependencies: Explicit dependency declarations to validate or inspect for async requirements.

        """
        return self._validate_explicit_dependencies(
            provider=concrete_type,
            provider_name=concrete_type.__qualname__,
            dependencies=dependencies,
            skip_first_parameter=False,
        )

    def validate_explicit_for_factory(
        self,
        factory: FactoryProvider[Any],
        dependencies: list[ProviderDependency],
    ) -> list[ProviderDependency]:
        """Validate explicit dependencies for a factory-based provider.

        Args:
            factory: Factory provider callable to inspect or validate.
            dependencies: Explicit dependency declarations to validate or inspect for async requirements.

        """
        return self._validate_explicit_dependencies(
            provider=factory,
            provider_name=self._provider_name(factory),
            dependencies=dependencies,
            skip_first_parameter=False,
        )

    def validate_explicit_for_generator(
        self,
        generator: GeneratorProvider[Any],
        dependencies: list[ProviderDependency],
    ) -> list[ProviderDependency]:
        """Validate explicit dependencies for a generator-based provider.

        Args:
            generator: Generator provider callable to inspect or validate.
            dependencies: Explicit dependency declarations to validate or inspect for async requirements.

        """
        return self._validate_explicit_dependencies(
            provider=generator,
            provider_name=self._provider_name(generator),
            dependencies=dependencies,
            skip_first_parameter=False,
        )

    def validate_explicit_for_context_manager(
        self,
        context_manager: ContextManagerProvider[Any],
        dependencies: list[ProviderDependency],
    ) -> list[ProviderDependency]:
        """Validate explicit dependencies for a context manager-based provider.

        Args:
            context_manager: Context manager provider callable to inspect or validate.
            dependencies: Explicit dependency declarations to validate or inspect for async requirements.

        """
        return self._validate_explicit_dependencies(
            provider=context_manager,
            provider_name=self._provider_name(context_manager),
            dependencies=dependencies,
            skip_first_parameter=False,
        )

    def _extract_dependencies(
        self,
        *,
        provider: Callable[..., Any],
        provider_name: str,
        skip_first_parameter: bool,
    ) -> list[ProviderDependency]:
        parameters = self._provider_parameters(
            provider=provider,
            skip_first_parameter=skip_first_parameter,
        )
        annotations, annotation_error = self._resolved_type_hints(provider)
        dependencies: list[ProviderDependency] = []

        for parameter in parameters:
            provides = self._resolve_parameter_annotation(
                parameter=parameter,
                annotations=annotations,
                annotation_error=annotation_error,
                provider_name=provider_name,
            )
            if provides is _MISSING_ANNOTATION:
                continue

            dependencies.append(
                ProviderDependency(
                    provides=provides,
                    parameter=parameter,
                ),
            )

        return dependencies

    def _validate_explicit_dependencies(
        self,
        *,
        provider: Callable[..., Any],
        provider_name: str,
        dependencies: list[ProviderDependency],
        skip_first_parameter: bool,
    ) -> list[ProviderDependency]:
        parameters = self._provider_parameters(
            provider=provider,
            skip_first_parameter=skip_first_parameter,
        )
        parameters_by_name = {parameter.name: parameter for parameter in parameters}
        validated_dependencies_by_name: dict[str, ProviderDependency] = {}

        for dependency in dependencies:
            parameter_name = dependency.parameter.name
            signature_parameter = parameters_by_name.get(parameter_name)
            if signature_parameter is None:
                msg = (
                    f"Explicit dependency for unknown parameter '{parameter_name}' in "
                    f"provider '{provider_name}'."
                )
                raise DIWireInvalidProviderSpecError(msg)
            if parameter_name in validated_dependencies_by_name:
                msg = (
                    f"Explicit dependency for parameter '{parameter_name}' in "
                    f"provider '{provider_name}' is duplicated."
                )
                raise DIWireInvalidProviderSpecError(msg)
            if dependency.parameter.kind is not signature_parameter.kind:
                msg = (
                    f"Explicit dependency for parameter '{parameter_name}' in provider "
                    f"'{provider_name}' has kind '{dependency.parameter.kind}' but expected "
                    f"'{signature_parameter.kind}'."
                )
                raise DIWireInvalidProviderSpecError(msg)

            validated_dependencies_by_name[parameter_name] = ProviderDependency(
                provides=dependency.provides,
                parameter=signature_parameter,
            )

        missing_required_parameters = [
            parameter.name
            for parameter in parameters
            if self._is_required_parameter(parameter)
            and parameter.name not in validated_dependencies_by_name
        ]
        if missing_required_parameters:
            missing_parameters = ", ".join(f"'{name}'" for name in missing_required_parameters)
            msg = (
                f"Explicit dependencies for provider '{provider_name}' are incomplete. "
                f"Missing required parameters: {missing_parameters}."
            )
            raise DIWireProviderDependencyInferenceError(msg)

        return [
            validated_dependencies_by_name[parameter.name]
            for parameter in parameters
            if parameter.name in validated_dependencies_by_name
        ]

    def _resolve_parameter_annotation(
        self,
        *,
        parameter: Parameter,
        annotations: dict[str, Any],
        annotation_error: Exception | None,
        provider_name: str,
    ) -> Any:
        annotation = annotations.get(parameter.name, _MISSING_ANNOTATION)
        if annotation is not _MISSING_ANNOTATION:
            return annotation

        raw_annotation = parameter.annotation
        if raw_annotation is not Parameter.empty and not isinstance(raw_annotation, str):
            return raw_annotation

        if not self._is_required_parameter(parameter):
            return _MISSING_ANNOTATION

        error_message = (
            f"Unable to infer dependency for required parameter '{parameter.name}' "
            f"in provider '{provider_name}'. Add a type annotation or pass explicit dependencies."
        )
        if annotation_error is None:
            raise DIWireProviderDependencyInferenceError(error_message)
        msg = f"{error_message} Original annotation error: {annotation_error}"
        raise DIWireProviderDependencyInferenceError(msg) from annotation_error

    def _provider_parameters(
        self,
        *,
        provider: Callable[..., Any],
        skip_first_parameter: bool,
    ) -> tuple[Parameter, ...]:
        parameters = tuple(inspect.signature(provider).parameters.values())
        if (
            skip_first_parameter
            and parameters
            and parameters[0].name in _IMPLICIT_FIRST_PARAMETER_NAMES
        ):
            return parameters[1:]
        return parameters

    def _resolved_type_hints(
        self,
        provider: Callable[..., Any],
    ) -> tuple[dict[str, Any], Exception | None]:
        annotations: dict[str, Any] = {}
        annotation_error: Exception | None = None

        try:
            annotations = get_type_hints(provider, include_extras=True)
        except (AttributeError, NameError, TypeError) as error:
            annotation_error = error

        if inspect.isclass(provider):
            annotations, annotation_error = self._merge_concrete_type_callable_hints(
                concrete_type=provider,
                annotations=annotations,
                annotation_error=annotation_error,
            )

        return annotations, annotation_error

    def _merge_concrete_type_callable_hints(
        self,
        *,
        concrete_type: type[Any],
        annotations: dict[str, Any],
        annotation_error: Exception | None,
    ) -> tuple[dict[str, Any], Exception | None]:
        merged_annotations = dict(annotations)
        merged_error = annotation_error

        for callable_member_name in ("__call__", "__new__", "__init__"):
            callable_member = getattr(concrete_type, callable_member_name)
            try:
                member_annotations = get_type_hints(callable_member, include_extras=True)
            except (AttributeError, NameError, TypeError) as error:
                if merged_error is None:
                    merged_error = error
                continue
            for parameter_name, parameter_annotation in member_annotations.items():
                merged_annotations.setdefault(parameter_name, parameter_annotation)

        return merged_annotations, merged_error

    def _is_required_parameter(self, parameter: Parameter) -> bool:
        return (
            parameter.default is Parameter.empty
            and parameter.kind is not Parameter.VAR_POSITIONAL
            and parameter.kind is not Parameter.VAR_KEYWORD
        )

    def _provider_name(self, provider: Callable[..., Any]) -> str:
        return getattr(provider, "__qualname__", repr(provider))


@dataclass(slots=True)
class ProviderDependency:
    """Represent a resolved dependency key bound to a provider parameter."""

    provides: UserDependency
    parameter: Parameter


@dataclass(slots=True)
class ProviderReturnTypeExtractor:
    """Extracts return types from user-defined provider objects."""

    def is_factory_async(
        self,
        factory: FactoryProvider[Any],
    ) -> bool:
        """Check whether a factory provider itself is asynchronous.

        Args:
            factory: Factory provider callable to inspect or validate.

        """
        return inspect.iscoroutinefunction(factory) or self.return_annotation_matches_origins(
            provider=factory,
            expected_origins=(Awaitable, Coroutine),
        )

    def is_generator_async(
        self,
        generator: GeneratorProvider[Any],
    ) -> bool:
        """Check whether a generator provider itself is asynchronous.

        Args:
            generator: Generator provider callable to inspect or validate.

        """
        return inspect.isasyncgenfunction(generator) or self.return_annotation_matches_origins(
            provider=generator,
            expected_origins=(AsyncGenerator,),
        )

    def is_context_manager_async(
        self,
        context_manager: ContextManagerProvider[Any],
    ) -> bool:
        """Check whether a context manager provider itself is asynchronous.

        Args:
            context_manager: Context manager provider callable to inspect or validate.

        """
        unwrapped_context_manager = inspect.unwrap(context_manager)
        if inspect.isasyncgenfunction(unwrapped_context_manager):
            return True
        if inspect.iscoroutinefunction(unwrapped_context_manager):
            return True
        if self.return_annotation_matches_origins(
            provider=unwrapped_context_manager,
            expected_origins=(AbstractAsyncContextManager, AsyncGenerator),
        ):
            return True

        if isinstance(unwrapped_context_manager, type) and (
            self._context_manager_mode(unwrapped_context_manager) == "async"
        ):
            return True

        return_annotation, _annotation_error = self._resolved_return_annotation(
            unwrapped_context_manager,
        )
        unwrapped_return_annotation = self.unwrap_annotated(return_annotation)
        if isinstance(unwrapped_return_annotation, type):
            return self._context_manager_mode(unwrapped_return_annotation) == "async"
        return False

    def is_any_dependency_async(
        self,
        dependencies: list[ProviderDependency],
    ) -> bool:
        """Check whether provider dependencies require asynchronous resolution.

        Args:
            dependencies: Explicit dependency declarations to validate or inspect for async requirements.

        """
        return any(
            self.annotation_matches_origins(
                annotation=dependency.provides,
                expected_origins=_ASYNC_RESOLVER_ORIGINS,
            )
            for dependency in dependencies
        )

    def extract_from_factory(
        self,
        factory: FactoryProvider[Any],
    ) -> Any:
        """Extract a return type from a factory-based provider.

        Args:
            factory: Factory provider callable to inspect or validate.

        """
        return_annotation, annotation_error = self._resolved_return_annotation(factory)
        provider_name = self._provider_name(factory)
        if return_annotation is _MISSING_ANNOTATION:
            self._raise_missing_return_annotation_error(
                provider_kind="factory",
                provider_name=provider_name,
                annotation_error=annotation_error,
            )

        unwrapped_return_type = self._unwrap_factory_return_type(return_annotation)
        if unwrapped_return_type is _MISSING_ANNOTATION:
            self._raise_invalid_return_annotation_error(
                provider_kind="factory",
                provider_name=provider_name,
                expected_annotations="`T`, `Awaitable[T]`, or `Coroutine[Any, Any, T]`",
                annotation_error=annotation_error,
            )

        return unwrapped_return_type

    def extract_from_generator(
        self,
        generator: GeneratorProvider[Any],
    ) -> Any:
        """Extract a return type from a generator-based provider.

        Args:
            generator: Generator provider callable to inspect or validate.

        """
        return_annotation, annotation_error = self._resolved_return_annotation(generator)
        provider_name = self._provider_name(generator)
        if return_annotation is _MISSING_ANNOTATION:
            self._raise_missing_return_annotation_error(
                provider_kind="generator",
                provider_name=provider_name,
                annotation_error=annotation_error,
            )

        yielded_type = self._extract_yielded_or_managed_type(
            return_annotation=return_annotation,
            expected_origins=(Generator, AsyncGenerator),
        )
        if yielded_type is _MISSING_ANNOTATION:
            self._raise_invalid_return_annotation_error(
                provider_kind="generator",
                provider_name=provider_name,
                expected_annotations="`Generator[T, None, None]` or `AsyncGenerator[T, None]`",
                annotation_error=annotation_error,
            )

        return yielded_type

    def extract_from_context_manager(
        self,
        context_manager: ContextManagerProvider[Any],
    ) -> Any:
        """Extract a return type from a context manager-based provider.

        Args:
            context_manager: Context manager provider callable to inspect or validate.

        """
        return_annotation, annotation_error = self._resolved_return_annotation(context_manager)
        provider_name = self._provider_name(context_manager)
        if return_annotation is not _MISSING_ANNOTATION:
            yielded_type = self._extract_yielded_or_managed_type(
                return_annotation=return_annotation,
                expected_origins=(
                    AbstractContextManager,
                    AbstractAsyncContextManager,
                    Generator,
                    AsyncGenerator,
                ),
            )
            if yielded_type is not _MISSING_ANNOTATION:
                return yielded_type

        if isinstance(context_manager, type):
            managed_type = self._infer_managed_type_from_cm_type(context_manager)
            if managed_type is not _MISSING_ANNOTATION:
                return managed_type

        unwrapped_return_annotation = self.unwrap_annotated(return_annotation)
        if isinstance(unwrapped_return_annotation, type):
            managed_type = self._infer_managed_type_from_cm_type(unwrapped_return_annotation)
            if managed_type is not _MISSING_ANNOTATION:
                return managed_type

        msg = (
            f"Unable to infer return type for context manager provider '{provider_name}'. "
            "Add a provider return annotation (`AbstractContextManager[T]`, "
            "`AbstractAsyncContextManager[T]`, `Generator[T, None, None]`, or "
            "`AsyncGenerator[T, None]`), annotate `__enter__` or `__aenter__` on the "
            "context manager class, or pass provides= explicitly."
        )
        self._raise_invalid_registration_error(msg=msg, annotation_error=annotation_error)
        return _MISSING_ANNOTATION  # pragma: no cover

    def return_annotation_matches_origins(
        self,
        *,
        provider: Callable[..., Any],
        expected_origins: tuple[type[Any], ...],
    ) -> bool:
        """Check whether provider return annotation origin matches one of expected origins.

        Args:
            provider: Provider callable or type whose return annotation is being checked.
            expected_origins: Allowed annotation origins for a successful match check.

        """
        return_annotation, _annotation_error = self._resolved_return_annotation(provider)
        if return_annotation is _MISSING_ANNOTATION:
            return False
        return self.annotation_matches_origins(
            annotation=return_annotation,
            expected_origins=expected_origins,
        )

    def annotation_matches_origins(
        self,
        *,
        annotation: Any,
        expected_origins: tuple[type[Any], ...],
    ) -> bool:
        """Check whether annotation origin matches one of expected origins.

        Args:
            annotation: Annotation value to inspect or normalize.
            expected_origins: Allowed annotation origins for a successful match check.

        """
        annotation = self.unwrap_annotated(annotation)
        origin = get_origin(annotation)
        if origin in expected_origins:
            return True
        return annotation in expected_origins

    def unwrap_annotated(
        self,
        annotation: Any,
    ) -> Any:
        """Recursively unwrap Annotated[T, ...] into T.

        Args:
            annotation: Annotation value to inspect or normalize.

        """
        if get_origin(annotation) is not Annotated:
            return annotation
        annotation_args = get_args(annotation)
        if (
            not annotation_args
        ):  # pragma: no cover - typing.Annotated always wraps at least one type
            return annotation
        return self.unwrap_annotated(annotation_args[0])

    def _is_self_annotation(
        self,
        annotation: Any,
    ) -> bool:
        unwrapped_annotation = self.unwrap_annotated(annotation)
        annotation_module = getattr(unwrapped_annotation, "__module__", None)
        if annotation_module not in {"typing", "typing_extensions"}:
            return False

        annotation_name = getattr(
            unwrapped_annotation,
            "__qualname__",
            getattr(unwrapped_annotation, "__name__", None),
        )
        return annotation_name == "Self"

    def _infer_managed_type_from_cm_type(
        self,
        cm_type: type[Any],
    ) -> Any:
        context_manager_mode = self._context_manager_mode(cm_type)
        if context_manager_mode == "none":
            return _MISSING_ANNOTATION

        enter_method_name = "__aenter__" if context_manager_mode == "async" else "__enter__"
        enter_method = cast("Callable[..., Any]", getattr(cm_type, enter_method_name))
        return_annotation, _annotation_error = self._resolved_return_annotation(enter_method)
        if return_annotation is _MISSING_ANNOTATION:
            return _MISSING_ANNOTATION

        managed_type = return_annotation
        if context_manager_mode == "async":
            managed_type = self._unwrap_factory_return_type(managed_type)
            if managed_type is _MISSING_ANNOTATION:
                return _MISSING_ANNOTATION

        if self._is_self_annotation(managed_type):
            return cm_type
        return managed_type

    def _context_manager_mode(
        self,
        cm_type: type[Any],
    ) -> Literal["sync", "async", "none"]:
        has_sync_methods = callable(getattr(cm_type, "__enter__", None)) and callable(
            getattr(cm_type, "__exit__", None),
        )
        has_async_methods = callable(getattr(cm_type, "__aenter__", None)) and callable(
            getattr(cm_type, "__aexit__", None),
        )

        if has_async_methods and not has_sync_methods:
            return "async"
        if has_sync_methods:
            return "sync"
        return "none"

    def _resolved_return_annotation(
        self,
        provider: Callable[..., Any],
    ) -> tuple[Any, Exception | None]:
        try:
            return_type_hints = get_type_hints(provider, include_extras=True)
            annotation_error: Exception | None = None
        except (AttributeError, NameError, TypeError) as error:
            return_type_hints = {}
            annotation_error = error

        resolved_return_annotation = return_type_hints.get("return", _MISSING_ANNOTATION)
        if resolved_return_annotation is not _MISSING_ANNOTATION:
            return resolved_return_annotation, annotation_error

        try:
            raw_return_annotation = inspect.signature(provider).return_annotation
        except (TypeError, ValueError) as error:
            if annotation_error is None:
                annotation_error = error
            return _MISSING_ANNOTATION, annotation_error

        if raw_return_annotation is inspect.Signature.empty or isinstance(
            raw_return_annotation,
            str,
        ):
            return _MISSING_ANNOTATION, annotation_error

        return raw_return_annotation, annotation_error

    def _unwrap_factory_return_type(
        self,
        return_annotation: Any,
    ) -> Any:
        origin = get_origin(return_annotation)
        annotation_args = get_args(return_annotation)
        if origin is Awaitable:
            if len(annotation_args) != 1:
                return _MISSING_ANNOTATION
            return annotation_args[0]
        if origin is Coroutine:
            if len(annotation_args) != _COROUTINE_ARGUMENT_COUNT:
                return _MISSING_ANNOTATION
            return annotation_args[_COROUTINE_RESULT_INDEX]
        return return_annotation

    def _extract_yielded_or_managed_type(
        self,
        *,
        return_annotation: Any,
        expected_origins: tuple[type[Any], ...],
    ) -> Any:
        origin = get_origin(return_annotation)
        if origin not in expected_origins:
            return _MISSING_ANNOTATION

        annotation_args = get_args(return_annotation)
        if len(annotation_args) < 1:
            return _MISSING_ANNOTATION
        return annotation_args[0]

    def _raise_missing_return_annotation_error(
        self,
        *,
        provider_kind: str,
        provider_name: str,
        annotation_error: Exception | None,
    ) -> None:
        msg = (
            f"Unable to infer return type for {provider_kind} provider '{provider_name}'. "
            "Add a return type annotation or pass provides= explicitly."
        )
        self._raise_invalid_registration_error(msg=msg, annotation_error=annotation_error)

    def _raise_invalid_return_annotation_error(
        self,
        *,
        provider_kind: str,
        provider_name: str,
        expected_annotations: str,
        annotation_error: Exception | None,
    ) -> None:
        msg = (
            f"Unable to infer return type for {provider_kind} provider '{provider_name}'. "
            f"Expected return annotation {expected_annotations}. "
            "Add a valid return annotation or pass provides= explicitly."
        )
        self._raise_invalid_registration_error(msg=msg, annotation_error=annotation_error)

    def _raise_invalid_registration_error(
        self,
        *,
        msg: str,
        annotation_error: Exception | None,
    ) -> None:
        if annotation_error is None:
            raise DIWireInvalidRegistrationError(msg)
        full_msg = f"{msg} Original annotation error: {annotation_error}"
        raise DIWireInvalidRegistrationError(full_msg) from annotation_error

    def _provider_name(self, provider: Callable[..., Any]) -> str:
        return getattr(provider, "__qualname__", repr(provider))
