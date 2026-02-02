from typing import Any

try:
    from pydantic_settings import BaseSettings as _PydanticSettingsBaseSettings
except ImportError:  # pragma: no cover
    _PydanticSettingsBaseSettings = None  # type: ignore[assignment]

try:
    from pydantic.v1 import BaseSettings as _PydanticV1BaseSettings
except ImportError:  # pragma: no cover - pydantic v1 not installed/incompatible
    try:
        from pydantic import BaseSettings as _PydanticV1BaseSettings
    except (
        ImportError,
        AttributeError,
    ):  # pragma: no cover - pydantic v1 not installed/incompatible
        _PydanticV1BaseSettings = None  # type: ignore[assignment]

if _PydanticSettingsBaseSettings is not None:
    BaseSettings: type[Any] = _PydanticSettingsBaseSettings  # type: ignore[assignment]
elif _PydanticV1BaseSettings is not None:  # type: ignore[unreachable] # pragma: no cover
    BaseSettings = _PydanticV1BaseSettings  # type: ignore[assignment]
else:

    class BaseSettings:  # type: ignore[no-redef] # noqa: D101 # pragma: no cover
        pass


PydanticV1BaseSettings: type[Any] | None = _PydanticV1BaseSettings

__all__ = ["BaseSettings", "PydanticV1BaseSettings"]
