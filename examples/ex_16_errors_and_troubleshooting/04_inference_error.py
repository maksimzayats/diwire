"""Focused example: ``DIWireProviderDependencyInferenceError``."""

from __future__ import annotations

from diwire import Container
from diwire.exceptions import DIWireProviderDependencyInferenceError


class Service:
    pass


def build_service(raw_value) -> Service:  # type: ignore[no-untyped-def]
    _ = raw_value
    return Service()


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    try:
        container.add_factory(build_service, provides=Service)
    except DIWireProviderDependencyInferenceError as error:
        error_name = type(error).__name__

    print(f"inference={error_name}")  # => inference=DIWireProviderDependencyInferenceError


if __name__ == "__main__":
    main()
