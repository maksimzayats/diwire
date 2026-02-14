"""Focused example: dataclass ``default_factory`` fallback in strict mode."""

from __future__ import annotations

from dataclasses import dataclass, field

from diwire import Container, DependencyRegistrationPolicy, Lifetime, MissingPolicy
from diwire.exceptions import DIWireDependencyNotRegisteredError


class ApiClient:
    pass


@dataclass(slots=True)
class ServiceWithFactoryDefault:
    client: ApiClient = field(default_factory=ApiClient)


_DEFAULT_CLIENT = ApiClient()


@dataclass(slots=True)
class ServiceWithValueDefault:
    client: ApiClient = _DEFAULT_CLIENT


def strict_container() -> Container:
    return Container(
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )


def main() -> None:
    container = strict_container()
    container.add(
        ServiceWithFactoryDefault,
        provides=ServiceWithFactoryDefault,
        lifetime=Lifetime.TRANSIENT,
    )

    resolved_from_factory = container.resolve(ServiceWithFactoryDefault)
    print(
        f"factory_default_used={isinstance(resolved_from_factory.client, ApiClient)}",
    )  # => factory_default_used=True

    registered_client = ApiClient()
    container.add_instance(registered_client, provides=ApiClient)
    resolved_with_registration = container.resolve(ServiceWithFactoryDefault)
    print(
        f"registered_overrides_factory={resolved_with_registration.client is registered_client}",
    )  # => registered_overrides_factory=True

    strict_value_default = strict_container()
    strict_value_default.add(ServiceWithValueDefault, provides=ServiceWithValueDefault)
    try:
        strict_value_default.resolve(ServiceWithValueDefault)
    except DIWireDependencyNotRegisteredError as error:
        print(
            f"value_default_stays_strict={type(error).__name__}",
        )  # => value_default_stays_strict=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
