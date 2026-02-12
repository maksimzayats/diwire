"""Focused example: unbound ``ContainerContext`` usage error."""

from __future__ import annotations

from diwire import ContainerContext
from diwire.exceptions import DIWireContainerNotSetError


class Service:
    pass


def main() -> None:
    context = ContainerContext()

    try:
        context.resolve(Service)
    except DIWireContainerNotSetError as error:
        error_name = type(error).__name__

    print(f"unbound_error={error_name}")  # => unbound_error=DIWireContainerNotSetError


if __name__ == "__main__":
    main()
