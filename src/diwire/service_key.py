from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, get_args, get_origin


@dataclass(slots=True, frozen=True)
class Component:
    """Named component marker for distinguishing multiple registrations of the same type."""

    value: Any


@dataclass(kw_only=True, slots=True, frozen=True)
class ServiceKey:
    """Unique identifier for a service in the container."""

    value: Any
    component: Component | None = None

    # Cache for ServiceKey instances to avoid repeated object creation
    _cache: ClassVar[dict[Any, "ServiceKey"]] = {}

    @classmethod
    def from_value(cls, value: Any) -> "ServiceKey":
        """Create a ServiceKey from a type, Annotated type, or existing ServiceKey."""
        if isinstance(value, ServiceKey):
            return value

        # Check cache FIRST (fast path for warmed caches)
        # This avoids expensive get_origin() call for cached values
        cached = cls._cache.get(value)
        if cached is not None:
            return cached

        # Only call get_origin if not cached
        origin = get_origin(value)
        if origin is not Annotated:
            # Simple type - cache and return
            key = cls(value=value)
            cls._cache[value] = key
            return key

        # Handle Annotated[T, ...] types
        args = get_args(value)
        inner_type = args[0]
        # Check metadata for Component
        for meta in args[1:]:
            if isinstance(meta, Component):
                # Don't cache types with Component (they may need different components)
                return cls(value=inner_type, component=meta)

        # Cache Annotated types without Component by the full value
        key = cls(value=inner_type)
        cls._cache[value] = key
        return key
