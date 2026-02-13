"""Focused example: provider calls follow scoped vs transient lifetime semantics."""

from __future__ import annotations

from diwire import Container, Lifetime, Provider, Scope


class Expensive:
    build_count = 0

    def __init__(self) -> None:
        type(self).build_count += 1


class UsesExpensiveProvider:
    def __init__(self, expensive_provider: Provider[Expensive]) -> None:
        self._expensive_provider = expensive_provider

    def get_expensive(self) -> Expensive:
        return self._expensive_provider()


def _run_scenario(*, lifetime: Lifetime) -> tuple[int, bool]:
    Expensive.build_count = 0
    container = Container()
    container.add(
        Expensive,
        provides=Expensive,
        scope=Scope.REQUEST,
        lifetime=lifetime,
    )
    container.add(
        UsesExpensiveProvider,
        provides=UsesExpensiveProvider,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        consumer = request_scope.resolve(UsesExpensiveProvider)
        first = consumer.get_expensive()
        second = consumer.get_expensive()

    return Expensive.build_count, first is second


def main() -> None:
    scoped_calls, scoped_same = _run_scenario(lifetime=Lifetime.SCOPED)
    transient_calls, transient_same = _run_scenario(lifetime=Lifetime.TRANSIENT)

    print(f"scoped_after_calls={scoped_calls}")  # => scoped_after_calls=1
    print(f"scoped_same_identity={scoped_same}")  # => scoped_same_identity=True
    print(f"transient_after_calls={transient_calls}")  # => transient_after_calls=2
    print(f"transient_same_identity={transient_same}")  # => transient_same_identity=False


if __name__ == "__main__":
    main()
