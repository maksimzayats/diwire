"""Explicit optional dependencies with Maybe[T].

This topic demonstrates:

1. ``resolve(Maybe[T])`` returning ``None`` when ``T`` is not registered.
2. Constructor defaults being honored for missing ``Maybe[T]`` dependencies.
3. Missing ``Maybe[T]`` dependencies without defaults resolving as ``None``.
4. Registered values overriding defaults.
5. ``T | None`` (Optional) staying strict and raising when unregistered.
"""

from __future__ import annotations

from diwire import Container, Maybe
from diwire.exceptions import DIWireDependencyNotRegisteredError


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


_DEFAULT_CLIENT = object()


class ServiceWithDefault:
    def __init__(self, client: Maybe[ApiClient] = _DEFAULT_CLIENT) -> None:
        self.client = client


class ServiceWithoutDefault:
    def __init__(self, client: Maybe[ApiClient]) -> None:
        self.client = client


def strict_container() -> Container:
    return Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=False,
    )


def main() -> None:
    container = strict_container()

    print(f"missing_maybe={container.resolve(Maybe[ApiClient])!r}")  # => missing_maybe=None

    container.add_concrete(ServiceWithDefault, provides=ServiceWithDefault)
    container.add_concrete(ServiceWithoutDefault, provides=ServiceWithoutDefault)

    with_default = container.resolve(ServiceWithDefault)
    without_default = container.resolve(ServiceWithoutDefault)
    print(
        f"default_honored={with_default.client is _DEFAULT_CLIENT}",
    )  # => default_honored=True
    print(f"missing_without_default={without_default.client!r}")  # => missing_without_default=None

    client = ApiClient(base_url="https://api.example.local")
    container.add_instance(client, provides=ApiClient)
    with_registered_client = container.resolve(ServiceWithDefault)
    print(
        f"registered_overrides_default={with_registered_client.client is client}",
    )  # => registered_overrides_default=True

    strict_optional = strict_container()
    try:
        strict_optional.resolve(ApiClient | None)
    except DIWireDependencyNotRegisteredError as error:
        print(
            f"optional_union_error={type(error).__name__}",
        )  # => optional_union_error=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
