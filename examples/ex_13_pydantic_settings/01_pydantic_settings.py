"""Pydantic settings auto-registration.

``BaseSettings`` subclasses are auto-registered by diwire as root-scope
singleton factories. Resolving the same settings type repeatedly returns the
same object instance.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings

from diwire import AutoregisterContainer


class AppSettings(BaseSettings):
    value: str = "settings"


def main() -> None:
    container = AutoregisterContainer()

    first = container.resolve(AppSettings)
    second = container.resolve(AppSettings)

    print(f"settings_singleton={first is second}")  # => settings_singleton=True
    print(f"settings_value={first.value}")  # => settings_value=settings


if __name__ == "__main__":
    main()
