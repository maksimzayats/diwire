"""Focused example: registration-time dependency autoregistration."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class Dependency:
    pass


@dataclass(slots=True)
class Root:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_dependencies=False)
    container.register_concrete(concrete_type=Root, autoregister_dependencies=True)

    registered = container._providers_registrations.find_by_type(Dependency) is not None
    print(f"autoregister_deps_on_register={registered}")  # => autoregister_deps_on_register=True


if __name__ == "__main__":
    main()
