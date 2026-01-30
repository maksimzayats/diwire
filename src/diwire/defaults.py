from typing import Any

from diwire.integrations.pydantic import BaseSettings
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

DEFAULT_AUTOREGISTER_REGISTRATION_FACTORIES = {
    BaseSettings: lambda cls: Registration(
        service_key=ServiceKey.from_value(cls),
        factory=lambda: cls(),
        lifetime=Lifetime.SINGLETON,
    ),
}

DEFAULT_AUTOREGISTER_LIFETIME = Lifetime.TRANSIENT
