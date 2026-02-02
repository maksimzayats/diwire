from collections.abc import Callable
from typing import Any

from diwire.integrations.pydantic import BaseSettings, PydanticV1BaseSettings
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Lifetime

DEFAULT_AUTOREGISTER_IGNORES: set[type[Any]] = {
    int,
    str,
    float,
    bool,
    list,
    dict,
    set,
    tuple,
}

DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES: dict[type[Any], Callable[[Any], Registration]] = {  # type: ignore[assignment]
    BaseSettings: lambda cls: Registration(
        service_key=ServiceKey.from_value(cls),
        factory=lambda: cls(),
        lifetime=Lifetime.SINGLETON,
    ),
}

if (  # pragma: no cover - pydantic v1 optional
    PydanticV1BaseSettings is not None and PydanticV1BaseSettings is not BaseSettings
):
    DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES[PydanticV1BaseSettings] = lambda cls: (
        Registration(
            service_key=ServiceKey.from_value(cls),
            factory=lambda: cls(),
            lifetime=Lifetime.SINGLETON,
        )
    )

DEFAULT_AUTOREGISTER_LIFETIME = Lifetime.TRANSIENT
