from __future__ import annotations

import inspect
import types
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass, field
from inspect import signature
from typing import (
    Annotated,
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Injected


@dataclass(kw_only=True, slots=True, frozen=True)
class _ResolvedDependencies:
    """Result of dependency resolution containing resolved values and any missing keys."""

    dependencies: dict[str, Any] = field(default_factory=dict)
    missing: list[ServiceKey] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _OpenGenericRegistration:
    """Open generic registration template."""

    service_key: ServiceKey
    registration: Registration
    typevars: tuple[Any, ...]


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


def _get_return_annotation(func: Callable[..., Any]) -> type | None:  # noqa: C901, PLR0911
    """Extract the return type annotation from a callable.

    Returns None if there's no return annotation or if the return type is None.
    Handles unwrapping of Optional, Union, AsyncGenerator, Generator, etc.
    """
    try:
        hints = get_type_hints(func, include_extras=True)
    except (NameError, TypeError, AttributeError):
        # NameError: unresolved forward references
        # TypeError: invalid type annotations
        # AttributeError: missing module or attribute
        return None

    return_type = hints.get("return")
    if return_type is None:
        return None

    # Handle NoneType - if return annotation is just None/NoneType, return None
    if return_type is type(None):
        return None

    # Unwrap async generator and generator types
    origin = get_origin(return_type)
    if origin is not None:
        # Handle Annotated[T, ...] - return full type to preserve metadata
        if origin is Annotated:
            return return_type  # type: ignore[return-value]
        # Handle Generator[YieldType, SendType, ReturnType] and AsyncGenerator[YieldType, SendType]
        if origin in (Generator, AsyncGenerator):
            args = get_args(return_type)
            if args:
                return args[0]  # Return the yield type
        # Handle union types - return the full union type, not just the origin
        if _is_union_type(return_type):
            return return_type  # type: ignore[return-value]
        # Handle other generic types - just return the origin if it's a class
        if isinstance(origin, type):
            return origin

    # Return the type if it's a class
    if isinstance(return_type, type):
        return return_type

    return None


def _unwrap_method_descriptor(
    obj: Any,
) -> tuple[Callable[..., Any] | None, Any]:
    """Unwrap staticmethod descriptors to get the underlying function.

    Returns:
        A tuple of (unwrapped_function, original_descriptor).
        If obj is not a descriptor, returns (None, None).

    """
    if isinstance(obj, staticmethod):
        return obj.__func__, obj
    return None, None


def _is_method_descriptor(obj: Any) -> bool:
    """Check if obj is a staticmethod descriptor."""
    return isinstance(obj, staticmethod)


def _has_injected_annotation(param: inspect.Parameter) -> bool:
    """Check if a parameter has Injected in its annotation.

    Handles both:
    - String annotations (from `from __future__ import annotations` / PEP 563)
    - Resolved Annotated types with Injected metadata
    """
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False

    # String annotation check (PEP 563)
    if isinstance(annotation, str):
        return "Injected" in annotation

    # Check for Annotated type with Injected metadata
    # For Annotated[T, ...], args[0] is T and args[1:] are the metadata
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return any(isinstance(arg, Injected) for arg in args[1:])

    return False


def _build_signature_without_injected(func: Callable[..., Any]) -> inspect.Signature:
    """Build a signature excluding parameters marked with Injected."""
    original_sig = signature(func)
    new_params = [p for p in original_sig.parameters.values() if not _has_injected_annotation(p)]
    return original_sig.replace(parameters=new_params)


def _is_typevar(arg: Any) -> bool:
    """Return True when arg is a TypeVar instance."""
    return isinstance(arg, TypeVar)


def _is_any_type(arg: Any) -> bool:
    """Return True when arg represents Any."""
    return arg is Any


def _is_union_type(value: Any) -> bool:
    """Check if value is a union type (str | int or Union[str, int])."""
    origin = get_origin(value)
    # Python 3.10+ uses types.UnionType for `X | Y` syntax
    # typing.Union is used for Union[X, Y] syntax
    return origin is types.UnionType or origin is Union


def _type_arg_matches_constraint(arg: Any, constraint: Any) -> bool:  # noqa: PLR0911
    """Check whether a type argument satisfies a bound/constraint."""
    if _is_any_type(arg) or _is_any_type(constraint):
        return True
    # For generic aliases (e.g., list[int]), compare structurally.
    # This check must come BEFORE isinstance(arg, type) because in Python 3.10,
    # types.GenericAlias passes isinstance(arg, type) but issubclass fails on it.
    arg_origin = get_origin(arg)
    constraint_origin = get_origin(constraint)
    if arg_origin is not None and constraint_origin is not None:
        if arg_origin != constraint_origin:
            return False
        arg_args = get_args(arg)
        constraint_args = get_args(constraint)
        if len(arg_args) != len(constraint_args):
            return False
        return all(
            _type_arg_matches_constraint(a, c)
            for a, c in zip(arg_args, constraint_args, strict=True)
        )
    if isinstance(arg, type) and isinstance(constraint, type):
        try:
            return issubclass(arg, constraint)
        except TypeError:
            return False
    return arg == constraint


def _get_generic_origin_and_args(value: Any) -> tuple[type | None, tuple[Any, ...]]:
    """Return (origin, args) for generic aliases, or (None, ()) otherwise."""
    origin = get_origin(value)
    if origin is None or origin is Annotated:
        return None, ()
    if not isinstance(origin, type):
        return None, ()
    return origin, get_args(value)
