"""Focused example: ``DIWireScopeMismatchError`` from root resolution."""

from __future__ import annotations

from diwire import Container, Scope
from diwire.exceptions import DIWireScopeMismatchError


class RequestDependency:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.register_concrete(
        RequestDependency,
        concrete_type=RequestDependency,
        scope=Scope.REQUEST,
    )

    try:
        container.resolve(RequestDependency)
    except DIWireScopeMismatchError as error:
        error_name = type(error).__name__

    print(f"scope_mismatch_error={error_name}")  # => scope_mismatch_error=DIWireScopeMismatchError


if __name__ == "__main__":
    main()
