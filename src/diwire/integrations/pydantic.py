from typing import Any, cast

_PydanticSettingsBaseSettings: type[Any] | None = None
try:
    from pydantic_settings import BaseSettings as _PydanticSettingsBaseSettings
except ImportError:  # pragma: no cover
    pass

_PydanticV1BaseSettings: type[Any] | None = None
try:
    from pydantic.v1 import BaseSettings as _PydanticV1BaseSettings  # type: ignore[assignment]
except ImportError:  # pragma: no cover - pydantic v1 not installed/incompatible
    try:
        from pydantic import BaseSettings as _PydanticV1BaseSettings  # type: ignore[assignment]
    except (ImportError, AttributeError):  # pragma: no cover - pydantic v1 not installed/incompatible
        pass

if _PydanticSettingsBaseSettings is not None:
    BaseSettings: type[Any] = cast("type[Any]", _PydanticSettingsBaseSettings)
elif _PydanticV1BaseSettings is not None:  # pragma: no cover
    BaseSettings = cast("type[Any]", _PydanticV1BaseSettings)
else:

    class BaseSettings:  # type: ignore[no-redef]  # noqa: D101  # pragma: no cover
        pass


PydanticV1BaseSettings: type[Any] | None = _PydanticV1BaseSettings

__all__ = ["BaseSettings", "PydanticV1BaseSettings"]
