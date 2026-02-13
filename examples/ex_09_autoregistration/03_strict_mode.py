"""Focused example: strict mode without concrete autoregistration."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, DependencyRegistrationPolicy, MissingPolicy
from diwire.exceptions import DIWireDependencyNotRegisteredError


class Dependency:
    pass


@dataclass(slots=True)
class Root:
    dependency: Dependency


def main() -> None:
    container = Container(
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    try:
        container.resolve(Root)
    except DIWireDependencyNotRegisteredError as error:
        error_name = type(error).__name__

    print(f"strict_missing={error_name}")  # => strict_missing=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
