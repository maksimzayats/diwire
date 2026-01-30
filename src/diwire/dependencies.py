import dataclasses
import inspect
from dataclasses import dataclass
from types import FunctionType, MethodType
from typing import Annotated, Any, TypeVar, get_args, get_origin, get_type_hints

from diwire.exceptions import DIWireDependencyExtractionError
from diwire.service_key import ServiceKey
from diwire.types import Injected

MIN_ANNOTATED_ARGS = 2


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    """Information about a constructor/function parameter."""

    service_key: ServiceKey
    has_default: bool
    typevar: Any | None = None


class DependenciesExtractor:
    """Extract type-hinted dependencies from classes and functions."""

    def __init__(self) -> None:
        # Cache for dependency extraction results
        self._deps_cache: dict[ServiceKey, dict[str, ServiceKey]] = {}
        self._deps_with_defaults_cache: dict[ServiceKey, dict[str, ParameterInfo]] = {}
        self._injected_deps_cache: dict[ServiceKey, dict[str, ServiceKey]] = {}

    def get_dependencies(self, service_key: ServiceKey) -> dict[str, ServiceKey]:
        """Get all type-hinted dependencies (for classes)."""
        cached = self._deps_cache.get(service_key)
        if cached is not None:
            return cached

        try:
            type_hints = self._get_type_hints(service_key)
        except (TypeError, NameError) as e:
            raise DIWireDependencyExtractionError(service_key, e) from e

        result: dict[str, ServiceKey] = {}
        for name, hint in type_hints.items():
            if name == "return":
                continue
            if self._extract_typevar_from_annotation(hint) is not None:
                continue
            result[name] = ServiceKey.from_value(hint)
        self._deps_cache[service_key] = result
        return result

    def get_dependencies_with_defaults(
        self,
        service_key: ServiceKey,
    ) -> dict[str, ParameterInfo]:
        """Get all type-hinted dependencies with default value information."""
        cached = self._deps_with_defaults_cache.get(service_key)
        if cached is not None:
            return cached

        try:
            type_hints = self._get_type_hints(service_key)
        except (TypeError, NameError) as e:
            raise DIWireDependencyExtractionError(service_key, e) from e
        defaults = self._get_parameter_defaults(service_key)

        result: dict[str, ParameterInfo] = {}
        for name, hint in type_hints.items():
            if name == "return":
                continue
            typevar = self._extract_typevar_from_annotation(hint)
            result[name] = ParameterInfo(
                service_key=ServiceKey.from_value(type if typevar is not None else hint),
                has_default=defaults.get(name, False),
                typevar=typevar,
            )
        self._deps_with_defaults_cache[service_key] = result
        return result

    def _get_parameter_defaults(self, service_key: ServiceKey) -> dict[str, bool]:
        """Get which parameters have default values."""
        value = service_key.value

        # Handle dataclasses
        if dataclasses.is_dataclass(value) and isinstance(value, type):
            defaults: dict[str, bool] = {}
            for f in dataclasses.fields(value):
                has_default = (
                    f.default is not dataclasses.MISSING
                    or f.default_factory is not dataclasses.MISSING
                )
                defaults[f.name] = has_default
            return defaults

        # Handle regular classes and functions
        # Use inspect.signature(cls) for classes with __signature__ (e.g. pydantic)
        if isinstance(value, type) and hasattr(value, "__signature__"):
            sig_target = value
        else:
            sig_target = self._get_init_func(service_key)
        try:
            sig = inspect.signature(sig_target)
        except (ValueError, TypeError):
            return {}

        return {
            name: param.default is not inspect.Parameter.empty
            for name, param in sig.parameters.items()
            if name != "self"
        }

    def get_injected_dependencies(self, service_key: ServiceKey) -> dict[str, ServiceKey]:
        """Get only dependencies marked with Injected (for functions)."""
        cached = self._injected_deps_cache.get(service_key)
        if cached is not None:
            return cached

        init_func = self._get_init_func(service_key)
        try:
            type_hints = get_type_hints(init_func, include_extras=True)
        except (NameError, TypeError):
            try:
                type_hints = get_type_hints(init_func)
            except (NameError, TypeError):
                type_hints = {}

        result = {}
        for name, hint in type_hints.items():
            if name == "return":
                continue
            actual_type = self._extract_injected_type(hint)
            if actual_type is not None:
                result[name] = ServiceKey.from_value(actual_type)
        self._injected_deps_cache[service_key] = result
        return result

    def _extract_injected_type(self, hint: Any) -> Any | None:
        """Extract the inner type if hint is Annotated[T, Injected()], otherwise return None."""
        if get_origin(hint) is not Annotated:
            return None

        args = get_args(hint)
        if len(args) < MIN_ANNOTATED_ARGS:
            return None  # pragma: no cover - Annotated requires at least 2 args

        # Check if any metadata is an Injected marker
        for metadata in args[1:]:
            if isinstance(metadata, Injected):
                return args[0]  # Return the actual type T from Annotated[T, Injected()]

        return None

    def _unwrap_annotated(self, hint: Any) -> Any:
        """Unwrap Annotated[T, ...] to T if present."""
        if get_origin(hint) is not Annotated:
            return hint
        args = get_args(hint)
        return args[0] if args else hint

    def _extract_typevar_from_annotation(self, hint: Any) -> TypeVar | None:
        """Return TypeVar if annotation is type[T] or Type[T]."""
        hint = self._unwrap_annotated(hint)
        origin = get_origin(hint)
        if origin is not type:
            return None
        args = get_args(hint)
        if len(args) != 1:
            return None
        arg = args[0]
        return arg if isinstance(arg, TypeVar) else None

    def _get_type_hints(self, service_key: ServiceKey) -> dict[str, Any]:
        """Get type hints for a service, with fallback for generated __init__ (e.g. pydantic).

        For non-class callables (functions/methods), returns get_type_hints(callable).
        For classes, checks if __init__ hints cover the class's __signature__ params. If not
        (generated __init__), falls back to class-level annotations filtered by signature.
        """
        value = service_key.value
        init_func = self._get_init_func(service_key)

        # For classes with __signature__ (e.g. pydantic), init hints may fail due to
        # generated __init__ with unresolvable forward refs — that's expected, we fall through.
        # For other callables, let the error propagate normally.
        has_signature = isinstance(value, type) and hasattr(value, "__signature__")
        try:
            init_hints = get_type_hints(init_func, include_extras=True)
        except (NameError, TypeError):
            if not has_signature:
                raise
            init_hints = None

        if not isinstance(value, type):
            return init_hints  # type: ignore[return-value]

        # Only apply fallback for classes that define __signature__ (e.g. pydantic BaseModel).
        # Regular classes and dataclasses don't set __signature__, so we use init_hints directly.
        if not has_signature:
            return init_hints  # type: ignore[return-value]

        # Get param names from the class's __signature__ (excluding variadic params)
        try:
            sig = value.__signature__  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
        except (ValueError, TypeError):  # pragma: no cover - defensive guard
            return init_hints or {}  # pragma: no cover

        sig_params = {
            name
            for name, p in sig.parameters.items()
            if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        }

        # If init hints match signature params (both directions), use them.
        # Otherwise fall through to class-level annotations.
        if init_hints is not None:
            init_hint_names = {n for n in init_hints if n != "return"}
            if sig_params == init_hint_names:
                return init_hints

        # Fallback: use class-level annotations filtered to signature params
        class_hints = get_type_hints(value, include_extras=True)
        return {name: hint for name, hint in class_hints.items() if name in sig_params}

    def _get_init_func(self, service_key: ServiceKey) -> Any:
        if isinstance(service_key.value, FunctionType | MethodType):
            return service_key.value

        return getattr(service_key.value, "__init__", service_key.value)
