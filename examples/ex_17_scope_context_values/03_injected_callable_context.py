"""Injected callables can consume FromContext values via diwire_context."""

from __future__ import annotations

from diwire import Container, FromContext, Scope, resolver_context


def main() -> None:
    Container(autoregister_concrete_types=False)

    @resolver_context.inject(scope=Scope.REQUEST)
    def handler(value: FromContext[int]) -> int:
        return value

    from_context = handler(diwire_context={int: 7})
    overridden = handler(value=8)

    print(f"from_context={from_context}")  # => from_context=7
    print(f"overridden={overridden}")  # => overridden=8


if __name__ == "__main__":
    main()
