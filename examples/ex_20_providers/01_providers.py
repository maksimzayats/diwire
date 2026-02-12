"""Lazy providers with Provider[T].

This topic demonstrates:

1. Breaking a circular dependency with ``Provider[T]``.
2. Deferring expensive construction until the provider is called.
3. Preserving scoped vs transient lifetime semantics through provider calls.
"""

from __future__ import annotations

from diwire import Container, Lifetime, Provider, Scope


class A:
    def __init__(self, b_provider: Provider[B]) -> None:
        self._b_provider = b_provider

    def get_b(self) -> B:
        return self._b_provider()


class B:
    def __init__(self, a: A) -> None:
        self.a = a


class Expensive:
    build_count = 0

    def __init__(self) -> None:
        type(self).build_count += 1


class UsesExpensiveProvider:
    def __init__(self, expensive_provider: Provider[Expensive]) -> None:
        self._expensive_provider = expensive_provider

    def get_expensive(self) -> Expensive:
        return self._expensive_provider()


def _run_expensive_scenario(*, lifetime: Lifetime) -> tuple[int, int, bool]:
    Expensive.build_count = 0
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        Expensive,
        provides=Expensive,
        scope=Scope.REQUEST,
        lifetime=lifetime,
    )
    container.add_concrete(
        UsesExpensiveProvider,
        provides=UsesExpensiveProvider,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        consumer = request_scope.resolve(UsesExpensiveProvider)
        before_calls = Expensive.build_count
        first = consumer.get_expensive()
        second = consumer.get_expensive()
        after_calls = Expensive.build_count
        same_identity = first is second
    return before_calls, after_calls, same_identity


def main() -> None:
    cycle_container = Container(autoregister_concrete_types=False)
    cycle_container.add_concrete(A)
    cycle_container.add_concrete(B)
    resolved_a = cycle_container.resolve(A)
    resolved_b = resolved_a.get_b()

    print(f"cycle_resolves={isinstance(resolved_b, B)}")  # => cycle_resolves=True
    print(f"cycle_same_a={resolved_b.a is resolved_a}")  # => cycle_same_a=True

    scoped_before, scoped_after, scoped_same = _run_expensive_scenario(
        lifetime=Lifetime.SCOPED,
    )
    print(f"scoped_before_call={scoped_before}")  # => scoped_before_call=0
    print(f"scoped_after_calls={scoped_after}")  # => scoped_after_calls=1
    print(f"scoped_same_identity={scoped_same}")  # => scoped_same_identity=True

    transient_before, transient_after, transient_same = _run_expensive_scenario(
        lifetime=Lifetime.TRANSIENT,
    )
    print(f"transient_before_call={transient_before}")  # => transient_before_call=0
    print(f"transient_after_calls={transient_after}")  # => transient_after_calls=2
    print(f"transient_same_identity={transient_same}")  # => transient_same_identity=False


if __name__ == "__main__":
    main()
