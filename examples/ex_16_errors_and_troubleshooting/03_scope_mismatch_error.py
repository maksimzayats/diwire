"""Focused example: ``DIWireScopeMismatchError``."""

from __future__ import annotations

from diwire import Container, DIWireScopeMismatchError, Scope


class RequestDependency:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
    )

    try:
        container.resolve(RequestDependency)
    except DIWireScopeMismatchError as error:
        error_name = type(error).__name__

    print(f"scope={error_name}")  # => scope=DIWireScopeMismatchError


if __name__ == "__main__":
    main()
