"""Focused example: ``Provider[T]`` defers expensive construction until called."""

from __future__ import annotations

from diwire import Container, Provider


class Expensive:
    build_count = 0

    def __init__(self) -> None:
        type(self).build_count += 1


class UsesExpensiveProvider:
    def __init__(self, expensive_provider: Provider[Expensive]) -> None:
        self._expensive_provider = expensive_provider

    def get_expensive(self) -> Expensive:
        return self._expensive_provider()


def main() -> None:
    Expensive.build_count = 0
    container = Container()
    container.add(Expensive)
    container.add(UsesExpensiveProvider)

    consumer = container.resolve(UsesExpensiveProvider)
    before_call = Expensive.build_count
    _ = consumer.get_expensive()
    after_call = Expensive.build_count

    print(f"lazy_before_call={before_call}")  # => lazy_before_call=0
    print(f"lazy_after_call={after_call}")  # => lazy_after_call=1


if __name__ == "__main__":
    main()
