"""Focused example: break a cycle with ``Provider[T]``."""

from __future__ import annotations

from diwire import Container, Provider


class A:
    def __init__(self, b_provider: Provider[B]) -> None:
        self._b_provider = b_provider

    def get_b(self) -> B:
        return self._b_provider()


class B:
    def __init__(self, a: A) -> None:
        self.a = a


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(A)
    container.add_concrete(B)

    resolved_a = container.resolve(A)
    resolved_b = resolved_a.get_b()

    print(f"cycle_resolves={isinstance(resolved_b, B)}")  # => cycle_resolves=True
    print(f"cycle_same_a={resolved_b.a is resolved_a}")  # => cycle_same_a=True


if __name__ == "__main__":
    main()
