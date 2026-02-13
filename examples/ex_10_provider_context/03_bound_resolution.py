"""Focused example: bound resolver resolution through ProviderContext."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, ProviderContext


@dataclass(slots=True)
class Service:
    value: str


def main() -> None:
    context = ProviderContext()
    container = Container(provider_context=context, autoregister_concrete_types=False)
    container.add_instance(Service("bound"), provides=Service)

    with container.compile():
        resolved = context.resolve(Service)
        print(f"bound_resolve_ok={resolved.value == 'bound'}")  # => bound_resolve_ok=True


if __name__ == "__main__":
    main()
