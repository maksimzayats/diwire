"""Focused example: ``DIWireDependencyNotRegisteredError``."""

from __future__ import annotations

from diwire import Container, DependencyRegistrationPolicy, MissingPolicy
from diwire.exceptions import DIWireDependencyNotRegisteredError


class MissingDependency:
    pass


def main() -> None:
    container = Container(
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )

    try:
        container.resolve(MissingDependency)
    except DIWireDependencyNotRegisteredError as error:
        error_name = type(error).__name__

    print(f"missing={error_name}")  # => missing=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
