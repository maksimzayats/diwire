try:
    from pydantic_settings import BaseSettings
except ImportError:

    class BaseSettings:  # type: ignore[no-redef]  # noqa: D101
        pass


__all__ = ["BaseSettings"]
