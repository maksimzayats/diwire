"""Focused example: registration-time dependency autoregistration."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, DependencyRegistrationPolicy


class Dependency:
    pass


@dataclass(slots=True)
class Root:
    dependency: Dependency


def main() -> None:
    container = Container()
    container.add_concrete(
        Root,
        dependency_registration_policy=DependencyRegistrationPolicy.REGISTER_RECURSIVE,
    )

    resolved = container.resolve(Root)
    autoregistered = isinstance(resolved.dependency, Dependency)
    print(
        f"autoregister_deps_on_register={autoregistered}",
    )  # => autoregister_deps_on_register=True


if __name__ == "__main__":
    main()
