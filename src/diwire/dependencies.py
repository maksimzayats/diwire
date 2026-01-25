import dataclasses
import inspect
from dataclasses import dataclass
from types import FunctionType, MethodType
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from diwire.exceptions import DIWireDependencyExtractionError
from diwire.service_key import ServiceKey
from diwire.types import FromDI

MIN_ANNOTATED_ARGS = 2


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    """Information about a constructor/function parameter."""

    service_key: ServiceKey
    has_default: bool


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

        init_func = self._get_init_func(service_key)
        try:
            type_hints = get_type_hints(init_func, include_extras=True)
        except (TypeError, NameError) as e:
            raise DIWireDependencyExtractionError(service_key, e) from e

        result = {
            name: ServiceKey.from_value(hint)
            for name, hint in type_hints.items()
            if name != "return"
        }
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

        init_func = self._get_init_func(service_key)
        try:
            type_hints = get_type_hints(init_func, include_extras=True)
        except (TypeError, NameError) as e:
            raise DIWireDependencyExtractionError(service_key, e) from e
        defaults = self._get_parameter_defaults(service_key)

        result = {
            name: ParameterInfo(
                service_key=ServiceKey.from_value(hint),
                has_default=defaults.get(name, False),
            )
            for name, hint in type_hints.items()
            if name != "return"
        }
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
        init_func = self._get_init_func(service_key)
        try:
            sig = inspect.signature(init_func)
        except (ValueError, TypeError):
            return {}

        return {
            name: param.default is not inspect.Parameter.empty
            for name, param in sig.parameters.items()
            if name != "self"
        }

    def get_injected_dependencies(self, service_key: ServiceKey) -> dict[str, ServiceKey]:
        """Get only dependencies marked with FromDI (for functions)."""
        cached = self._injected_deps_cache.get(service_key)
        if cached is not None:
            return cached

        init_func = self._get_init_func(service_key)
        type_hints = get_type_hints(init_func, include_extras=True)

        result = {}
        for name, hint in type_hints.items():
            if name == "return":
                continue
            actual_type = self._extract_from_di_type(hint)
            if actual_type is not None:
                result[name] = ServiceKey.from_value(actual_type)
        self._injected_deps_cache[service_key] = result
        return result

    def _extract_from_di_type(self, hint: Any) -> Any | None:
        """Extract the inner type if hint is Annotated[T, FromDI()], otherwise return None."""
        if get_origin(hint) is not Annotated:
            return None

        args = get_args(hint)
        if len(args) < MIN_ANNOTATED_ARGS:
            return None  # pragma: no cover - Annotated requires at least 2 args

        # Check if any metadata is a FromDI marker
        for metadata in args[1:]:
            if isinstance(metadata, FromDI):
                return args[0]  # Return the actual type T from Annotated[T, FromDI()]

        return None

    def _get_init_func(self, service_key: ServiceKey) -> Any:
        if isinstance(service_key.value, FunctionType | MethodType):
            return service_key.value

        return getattr(service_key.value, "__init__", service_key)
