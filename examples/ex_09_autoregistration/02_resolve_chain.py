"""Focused example: resolve-time autoregistration of a dependency chain."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class Leaf:
    pass


@dataclass(slots=True)
class Branch:
    leaf: Leaf


@dataclass(slots=True)
class Root:
    branch: Branch


def main() -> None:
    container = Container()
    resolved = container.resolve(Root)
    print(
        f"autoregister_chain={isinstance(resolved.branch.leaf, Leaf)}",
    )  # => autoregister_chain=True


if __name__ == "__main__":
    main()
