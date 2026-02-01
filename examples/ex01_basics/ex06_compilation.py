"""Compilation (precomputing providers) in diwire.

Demonstrates:
- manual compilation via container.compile()
- disabling auto-compilation via Container(auto_compile=False)
"""

from dataclasses import dataclass

from diwire import Container, Lifetime


@dataclass
class ServiceA:
    value: str = "A"


@dataclass
class ServiceB:
    a: ServiceA


def main() -> None:
    # Turn off auto-compilation so we can show the explicit call.
    container = Container(auto_compile=False)

    container.register(ServiceA, lifetime=Lifetime.SINGLETON)
    container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

    # Works before compilation (reflection-based resolution).
    b1 = container.resolve(ServiceB)
    print(f"Before compile(): b1.a.value={b1.a.value!r}")

    # Precompute the dependency graph for maximum throughput.
    container.compile()

    b2 = container.resolve(ServiceB)
    print(f"After compile():  b2.a.value={b2.a.value!r}")

    # Transient behavior is unchanged: new ServiceB each time.
    print(f"Transient preserved: {b1 is not b2}")

    # Singleton behavior is unchanged: same ServiceA.
    print(f"Singleton preserved: {b1.a is b2.a}")


if __name__ == "__main__":
    main()

