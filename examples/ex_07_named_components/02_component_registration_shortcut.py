"""Register components ergonomically with ``component=...``.

This example shows that registration can use ``component=...`` while runtime
resolution and injection keys remain ``Annotated[..., Component(...)]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container, Injected, provider_context


@dataclass(slots=True)
class Cache:
    backend: str


PrimaryCache = Annotated[Cache, Component("primary")]
FallbackCache = Annotated[Cache, Component("fallback")]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(Cache(backend="redis"), provides=Cache, component="primary")
    container.add_instance(Cache(backend="memory"), provides=Cache, component=Component("fallback"))

    @provider_context.inject
    def load(
        primary: Injected[PrimaryCache],
        fallback: Injected[FallbackCache],
    ) -> tuple[str, str]:
        return primary.backend, fallback.backend

    primary_backend, fallback_backend = load()
    print(f"primary={primary_backend}")  # => primary=redis
    print(f"fallback={fallback_backend}")  # => fallback=memory
    print(f"resolved={container.resolve(PrimaryCache).backend}")  # => resolved=redis


if __name__ == "__main__":
    main()
