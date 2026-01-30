from dataclasses import dataclass
from typing import Any

from diwire.types import Factory, Lifetime


@dataclass(kw_only=True, slots=True)
class Registration:
    """Configuration for how a service should be instantiated."""

    service_key: Any
    lifetime: Lifetime
    instance: Any | None = None
    factory: Factory | None = None
    scope: str | None = None
    is_async: bool = False
    concrete_type: type | None = None
    typevar_map: dict[Any, Any] | None = None
