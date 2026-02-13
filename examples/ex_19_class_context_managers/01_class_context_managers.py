"""Class-based context manager registration with inferred managed type.

This module demonstrates:

1. Registering a class context manager directly via ``add_context_manager(Service)``.
2. Inferring ``provides`` from ``Service.__enter__``.
3. Request-scoped caching behavior (same instance within one request scope).
"""

from __future__ import annotations

from types import TracebackType

from typing_extensions import Self

from diwire import Container, Lifetime, Scope


class Service:
    def __init__(self) -> None:
        print("new Service")  # => new Service

    def __enter__(self) -> Self:
        print("Entering Service context")  # => Entering Service context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        print("Exiting Service context")  # => Exiting Service context


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_context_manager(
        Service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        service_1 = request_scope.resolve(Service)
        service_2 = request_scope.resolve(Service)
        same_instance = service_1 is service_2
    print(f"same_instance={same_instance}")  # => same_instance=True


if __name__ == "__main__":
    main()
