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
    container.add_concrete(Root, autoregister_dependencies=True)

    resolved = container.resolve(Root)
    autoregistered = isinstance(resolved.dependency, Dependency)
    print(
        f"autoregister_deps_on_register={autoregistered}",
    )  # => autoregister_deps_on_register=True


if __name__ == "__main__":
    main()
