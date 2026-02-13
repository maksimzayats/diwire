"""Compilation caching and invalidation.

``Container.compile()`` caches a root resolver for the current provider graph.
When registrations change, compilation is invalidated and a new resolver is
built on the next compile/resolve call.
"""

from __future__ import annotations

from diwire import Container


class FirstService:
    pass


class SecondService:
    pass


def main() -> None:
    container = Container()
    container.add_concrete(FirstService, provides=FirstService)

    compiled_first = container.compile()
    compiled_second = container.compile()
    print(f"compile_cached={compiled_first is compiled_second}")  # => compile_cached=True

    container.add_concrete(SecondService, provides=SecondService)
    compiled_third = container.compile()
    print(
        f"compile_invalidated={compiled_third is not compiled_first}",
    )  # => compile_invalidated=True


if __name__ == "__main__":
    main()
