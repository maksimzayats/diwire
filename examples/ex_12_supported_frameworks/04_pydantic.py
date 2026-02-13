"""Focused example: pydantic v2 model field dependency extraction."""

from __future__ import annotations

import pydantic

from diwire import Container


class Dependency:
    pass


class Consumer(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    dependency: Dependency


def main() -> None:
    container = Container()
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(
        f"pydantic_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => pydantic_ok=True


if __name__ == "__main__":
    main()
