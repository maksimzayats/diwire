"""Circular Dependency Detection.

Demonstrates how diwire detects and reports circular dependencies.
"""

from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireCircularDependencyError


# Circular dependency: ServiceA -> ServiceB -> ServiceA
@dataclass
class ServiceA:
    """Service that depends on ServiceB."""

    b: "ServiceB"


@dataclass
class ServiceB:
    """Service that depends on ServiceA (creating a cycle)."""

    a: ServiceA


def main() -> None:
    container = Container()
    container.register(ServiceA)
    container.register(ServiceB)

    print("Attempting to resolve circular dependency chain:")
    print("  ServiceA -> ServiceB -> ServiceA")
    print()

    try:
        container.resolve(ServiceA)
    except DIWireCircularDependencyError as e:
        print("DIWireCircularDependencyError caught!")
        print(f"  Service key: {e.service_key}")
        print(f"  Resolution chain: {' -> '.join(str(k) for k in e.resolution_chain)}")

    # How to avoid: use factories, lazy loading, or restructure dependencies
    print("\nSolutions to avoid circular dependencies:")
    print("  1. Restructure code to break the cycle")
    print("  2. Use a factory to lazily create one of the services")
    print("  3. Introduce an interface/protocol to invert the dependency")


if __name__ == "__main__":
    main()
