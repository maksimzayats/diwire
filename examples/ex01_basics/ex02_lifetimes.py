"""Service Lifetimes in DIWire.

Demonstrates the difference between:
- TRANSIENT: New instance on every resolve
- SINGLETON: Same instance for entire container lifetime
"""

from diwire import Container, Lifetime


class TransientService:
    """Created fresh on each resolution."""


class SingletonService:
    """Shared across all resolutions."""


def main() -> None:
    container = Container(autoregister=False)

    # TRANSIENT: new instance every time
    container.register(TransientService, lifetime=Lifetime.TRANSIENT)

    t1 = container.resolve(TransientService)
    t2 = container.resolve(TransientService)
    t3 = container.resolve(TransientService)

    print("TRANSIENT instances:")
    print(f"  t1 id: {id(t1)}")
    print(f"  t2 id: {id(t2)}")
    print(f"  t3 id: {id(t3)}")
    print(f"  All different: {t1 is not t2 is not t3}")

    # SINGLETON: same instance always
    container.register(SingletonService, lifetime=Lifetime.SINGLETON)

    s1 = container.resolve(SingletonService)
    s2 = container.resolve(SingletonService)
    s3 = container.resolve(SingletonService)

    print("\nSINGLETON instances:")
    print(f"  s1 id: {id(s1)}")
    print(f"  s2 id: {id(s2)}")
    print(f"  s3 id: {id(s3)}")
    print(f"  All same: {s1 is s2 is s3}")


if __name__ == "__main__":
    main()
