"""Injected callables can consume FromContext values via __diwire_context."""

from __future__ import annotations

from diwire import Container, FromContext, Scope


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    @container.inject(scope=Scope.REQUEST)
    def handler(value: FromContext[int]) -> int:
        return value

    from_context = handler(__diwire_context={int: 7})
    overridden = handler(value=8)

    print(f"from_context={from_context}")
    print(f"overridden={overridden}")


if __name__ == "__main__":
    main()
