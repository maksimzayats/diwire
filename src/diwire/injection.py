from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from diwire.markers import (
    InjectedMarker,
    is_from_context_annotation,
    strip_from_context_annotation,
)

_ANNOTATED_DEPENDENCY_MIN_ARGS = 2
INJECT_RESOLVER_KWARG = "__diwire_resolver"
INJECT_CONTEXT_KWARG = "__diwire_context"
INJECT_WRAPPER_MARKER = "__diwire_inject_wrapper__"


@dataclass(frozen=True, slots=True)
class InjectedParameter:
    """Injected parameter metadata for callable wrapper generation."""

    name: str
    dependency: Any


@dataclass(frozen=True, slots=True)
class ContextParameter:
    """Context parameter metadata for callable wrapper generation."""

    name: str
    dependency: Any


@dataclass(frozen=True, slots=True)
class InjectedCallableInspection:
    """Injection metadata derived from a callable signature and annotations."""

    signature: inspect.Signature
    injected_parameters: tuple[InjectedParameter, ...]
    context_parameters: tuple[ContextParameter, ...]
    public_signature: inspect.Signature


@dataclass(slots=True)
class InjectedCallableInspector:
    """Inspect callables for Injected[...] parameters and public signature filtering."""

    def inspect_callable(self, callable_obj: Callable[..., Any]) -> InjectedCallableInspection:
        """Build injection metadata and a public signature for a callable."""
        signature = inspect.signature(callable_obj)
        injected_parameters = self.extract_injected_parameters(callable_obj=callable_obj)
        context_parameters = self.extract_context_parameters(callable_obj=callable_obj)
        hidden_parameter_names = {
            injected_parameter.name for injected_parameter in injected_parameters
        }
        hidden_parameter_names.update(
            context_parameter.name for context_parameter in context_parameters
        )
        public_signature = self.build_public_injected_signature(
            signature=signature,
            hidden_parameter_names=hidden_parameter_names,
        )
        return InjectedCallableInspection(
            signature=signature,
            injected_parameters=injected_parameters,
            context_parameters=context_parameters,
            public_signature=public_signature,
        )

    def extract_injected_parameters(
        self,
        *,
        callable_obj: Callable[..., Any],
    ) -> tuple[InjectedParameter, ...]:
        """Extract injected parameter metadata from a callable."""
        signature = inspect.signature(callable_obj)
        resolved_annotations = self.resolved_annotations_for_injection(callable_obj=callable_obj)
        injected_parameters: list[InjectedParameter] = []
        for parameter in signature.parameters.values():
            annotation = resolved_annotations.get(parameter.name, parameter.annotation)
            dependency = self.resolve_injected_dependency(annotation=annotation)
            if dependency is None:
                continue
            injected_parameters.append(
                InjectedParameter(
                    name=parameter.name,
                    dependency=dependency,
                ),
            )

        return tuple(injected_parameters)

    def extract_context_parameters(
        self,
        *,
        callable_obj: Callable[..., Any],
    ) -> tuple[ContextParameter, ...]:
        """Extract FromContext[...] parameter metadata from a callable."""
        signature = inspect.signature(callable_obj)
        resolved_annotations = self.resolved_annotations_for_injection(callable_obj=callable_obj)
        context_parameters: list[ContextParameter] = []
        for parameter in signature.parameters.values():
            annotation = resolved_annotations.get(parameter.name, parameter.annotation)
            dependency = self.resolve_from_context_dependency(annotation=annotation)
            if dependency is None:
                continue
            context_parameters.append(
                ContextParameter(
                    name=parameter.name,
                    dependency=dependency,
                ),
            )
        return tuple(context_parameters)

    def resolved_annotations_for_injection(
        self,
        *,
        callable_obj: Callable[..., Any],
    ) -> dict[str, Any]:
        """Resolve callable annotations with extras, falling back to an empty mapping."""
        try:
            return get_type_hints(callable_obj, include_extras=True)
        except (AttributeError, NameError, TypeError):
            return {}

    def resolve_injected_dependency(self, *, annotation: Any) -> Any | None:
        """Resolve Injected[...] annotations to dependency keys."""
        if annotation is inspect.Signature.empty or isinstance(annotation, str):
            return None
        if get_origin(annotation) is not Annotated:
            return None

        annotation_args = get_args(annotation)
        if len(annotation_args) < _ANNOTATED_DEPENDENCY_MIN_ARGS:
            return None
        parameter_type = annotation_args[0]
        metadata = annotation_args[1:]
        if not any(isinstance(item, InjectedMarker) for item in metadata):
            return None

        filtered_metadata = tuple(item for item in metadata if not isinstance(item, InjectedMarker))
        if not filtered_metadata:
            return parameter_type
        return self.build_annotated_type(parameter_type=parameter_type, metadata=filtered_metadata)

    def resolve_from_context_dependency(self, *, annotation: Any) -> Any | None:
        """Resolve FromContext[...] annotations to context keys."""
        if annotation is inspect.Signature.empty or isinstance(annotation, str):
            return None
        if not is_from_context_annotation(annotation):
            return None
        _ = strip_from_context_annotation(annotation)
        return annotation

    def build_annotated_type(
        self,
        *,
        parameter_type: Any,
        metadata: tuple[Any, ...],
    ) -> Any:
        """Build an Annotated type preserving metadata except Injected marker."""
        annotation_params = (parameter_type, *metadata)
        try:
            return Annotated.__class_getitem__(annotation_params)  # type: ignore[attr-defined]
        except AttributeError:
            return Annotated.__getitem__(annotation_params)  # type: ignore[attr-defined]

    def build_public_injected_signature(
        self,
        *,
        signature: inspect.Signature,
        hidden_parameter_names: set[str],
    ) -> inspect.Signature:
        """Build a signature that hides injected parameters."""
        filtered_parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.name not in hidden_parameter_names
        ]
        return signature.replace(parameters=filtered_parameters)
