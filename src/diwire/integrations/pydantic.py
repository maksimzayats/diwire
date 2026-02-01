from typing import Any, cast

try:
    from pydantic_settings import BaseSettings as _PydanticSettingsBaseSettings
except ImportError:  # pragma: no cover
    _PydanticSettingsBaseSettings = None  # type: ignore[assignment, misc]

try:
    from pydantic.v1 import BaseSettings as _PydanticV1BaseSettings
except ImportError:  # pragma: no cover - pydantic v1 not installed/incompatible
    try:
        from pydantic import BaseSettings as _PydanticV1BaseSettings
    except (ImportError, AttributeError):  # pragma: no cover - pydantic v1 not installed/incompatible
        _PydanticV1BaseSettings = None  # type: ignore[assignment]

if _PydanticSettingsBaseSettings is not None:
    BaseSettings: type[Any] = cast("type[Any]", _PydanticSettingsBaseSettings)
elif _PydanticV1BaseSettings is not None:  # type: ignore[unreachable]  # pragma: no cover
    BaseSettings = cast("type[Any]", _PydanticV1BaseSettings)
else:

    class BaseSettings:  # type: ignore[no-redef]  # noqa: D101  # pragma: no cover
        pass


PydanticV1BaseSettings: type[Any] | None = (
    cast("type[Any]", _PydanticV1BaseSettings) if _PydanticV1BaseSettings is not None else None
)

__all__ = ["BaseSettings", "PydanticV1BaseSettings"]
