from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum, auto
from inspect import Parameter
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    TypeAlias,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from diwire.exceptions import (
    DIWireInvalidProviderSpecError,
    DIWireInvalidRegistrationError,
    DIWireProviderDependencyInferenceError,
)
from diwire.lock_mode import LockMode
from diwire.scope import BaseScope

T = TypeVar("T")

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

ContextManagerProvider: TypeAlias = (
    Callable[..., AbstractContextManager[T]] | Callable[..., AbstractAsyncContextManager[T]]
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
    """A specification of a provider in the dependency injection system."""

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
    """Defines the lifetime of a service in the container."""

    TRANSIENT = auto()
    """A new instance is created every time the service is requested."""

    SINGLETON = auto()
    """A single instance is created and shared for the lifetime of the container."""

    SCOPED = auto()
    """Instance is shared within a scope, different instances across scopes."""


class ProvidersRegistrations:
    """Holds all provider specifications registered in the container."""

    def __init__(self) -> None:
        self._registrations_by_type: dict[UserDependency, ProviderSpec] = {}
        self._registrations_by_slot: dict[int, ProviderSpec] = {}

    def add(self, spec: ProviderSpec) -> None:
        """Add a new provider specification to the registrations."""
        self._registrations_by_type[spec.provides] = spec
        self._registrations_by_slot[spec.slot] = spec
        self._refresh_needs_cleanup_flags()

    def get_by_type(self, dep_type: UserDependency) -> ProviderSpec:
        """Get a provider specification by the type of dependency it provides."""
        return self._registrations_by_type[dep_type]

    def find_by_type(self, dep_type: UserDependency) -> ProviderSpec | None:
        """Get a provider specification by dependency type, if it exists."""
        return self._registrations_by_type.get(dep_type)

    def get_by_slot(self, slot: int) -> ProviderSpec:
        """Get a provider specification by its unique slot number."""
        return self._registrations_by_slot[slot]

    def get_by_scope(self, scope: BaseScope | None) -> list[ProviderSpec]:
        """Get all provider specifications registered for a specific scope."""
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
        """Extract dependencies from a concrete type-based provider."""
        init_callable = concrete_type.__init__
        return self._extract_dependencies(
            provider=init_callable,
            provider_name=concrete_type.__qualname__,
            skip_first_parameter=True,
        )

    def extract_from_factory(
        self,
        factory: FactoryProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a factory-based provider."""
        return self._extract_dependencies(
            provider=factory,
            provider_name=self._provider_name(factory),
            skip_first_parameter=False,
        )

    def extract_from_generator(
        self,
        generator: GeneratorProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a generator-based provider."""
        return self._extract_dependencies(
            provider=generator,
            provider_name=self._provider_name(generator),
            skip_first_parameter=False,
        )

    def extract_from_context_manager(
        self,
        context_manager: ContextManagerProvider[Any],
    ) -> list[ProviderDependency]:
        """Extract dependencies from a context manager-based provider."""
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
        """Validate explicit dependencies for a concrete type-based provider."""
        init_callable = concrete_type.__init__
        return self._validate_explicit_dependencies(
            provider=init_callable,
            provider_name=concrete_type.__qualname__,
            dependencies=dependencies,
            skip_first_parameter=True,
        )

    def validate_explicit_for_factory(
        self,
        factory: FactoryProvider[Any],
        dependencies: list[ProviderDependency],
    ) -> list[ProviderDependency]:
        """Validate explicit dependencies for a factory-based provider."""
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
        """Validate explicit dependencies for a generator-based provider."""
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
        """Validate explicit dependencies for a context manager-based provider."""
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
        try:
            return get_type_hints(provider, include_extras=True), None
        except (AttributeError, NameError, TypeError) as error:
            return {}, error

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
    """Represents a dependency required by a provider."""

    provides: UserDependency
    parameter: Parameter


@dataclass(slots=True)
class ProviderReturnTypeExtractor:
    """Extracts return types from user-defined provider objects."""

    def is_factory_async(
        self,
        factory: FactoryProvider[Any],
    ) -> bool:
        """Check whether a factory provider itself is asynchronous."""
        return inspect.iscoroutinefunction(factory) or self.return_annotation_matches_origins(
            provider=factory,
            expected_origins=(Awaitable, Coroutine),
        )

    def is_generator_async(
        self,
        generator: GeneratorProvider[Any],
    ) -> bool:
        """Check whether a generator provider itself is asynchronous."""
        return inspect.isasyncgenfunction(generator) or self.return_annotation_matches_origins(
            provider=generator,
            expected_origins=(AsyncGenerator,),
        )

    def is_context_manager_async(
        self,
        context_manager: ContextManagerProvider[Any],
    ) -> bool:
        """Check whether a context manager provider itself is asynchronous."""
        unwrapped_context_manager = inspect.unwrap(context_manager)
        if inspect.isasyncgenfunction(unwrapped_context_manager):
            return True
        if inspect.iscoroutinefunction(unwrapped_context_manager):
            return True
        return self.return_annotation_matches_origins(
            provider=unwrapped_context_manager,
            expected_origins=(AbstractAsyncContextManager, AsyncGenerator),
        )

    def is_any_dependency_async(
        self,
        dependencies: list[ProviderDependency],
    ) -> bool:
        """Check whether provider dependencies require asynchronous resolution."""
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
        """Extract a return type from a factory-based provider."""
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
        """Extract a return type from a generator-based provider."""
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
        """Extract a return type from a context manager-based provider."""
        return_annotation, annotation_error = self._resolved_return_annotation(context_manager)
        provider_name = self._provider_name(context_manager)
        if return_annotation is _MISSING_ANNOTATION:
            self._raise_missing_return_annotation_error(
                provider_kind="context manager",
                provider_name=provider_name,
                annotation_error=annotation_error,
            )

        yielded_type = self._extract_yielded_or_managed_type(
            return_annotation=return_annotation,
            expected_origins=(
                AbstractContextManager,
                AbstractAsyncContextManager,
                Generator,
                AsyncGenerator,
            ),
        )
        if yielded_type is _MISSING_ANNOTATION:
            self._raise_invalid_return_annotation_error(
                provider_kind="context manager",
                provider_name=provider_name,
                expected_annotations=(
                    "`AbstractContextManager[T]`, `AbstractAsyncContextManager[T]`, "
                    "`Generator[T, None, None]`, or `AsyncGenerator[T, None]`"
                ),
                annotation_error=annotation_error,
            )

        return yielded_type

    def return_annotation_matches_origins(
        self,
        *,
        provider: Callable[..., Any],
        expected_origins: tuple[type[Any], ...],
    ) -> bool:
        """Check whether provider return annotation origin matches one of expected origins."""
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
        """Check whether annotation origin matches one of expected origins."""
        annotation = self.unwrap_annotated(annotation)
        origin = get_origin(annotation)
        if origin in expected_origins:
            return True
        return annotation in expected_origins

    def unwrap_annotated(
        self,
        annotation: Any,
    ) -> Any:
        """Recursively unwrap Annotated[T, ...] into T."""
        if get_origin(annotation) is not Annotated:
            return annotation
        annotation_args = get_args(annotation)
        if (
            not annotation_args
        ):  # pragma: no cover - typing.Annotated always wraps at least one type
            return annotation
        return self.unwrap_annotated(annotation_args[0])

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
