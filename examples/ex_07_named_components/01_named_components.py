"""Named components with ``Component("name")`` and ``Annotated`` keys.

This module demonstrates how to register multiple implementations of the same
base type and resolve/inject them using component-qualified dependency keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container, Injected


@dataclass(slots=True)
class UserStore:
    backend: str

    def get_user(self, user_id: int) -> str:
        return f"{self.backend}:user:{user_id}"


PrimaryStore = Annotated[UserStore, Component("primary")]
FallbackStore = Annotated[UserStore, Component("fallback")]


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_factory(lambda: UserStore(backend="redis"), provides=PrimaryStore)
    container.add_factory(lambda: UserStore(backend="memory"), provides=FallbackStore)

    @container.inject
    def load_users(
        primary_store: Injected[PrimaryStore],
        fallback_store: Injected[FallbackStore],
    ) -> tuple[str, str]:
        return primary_store.get_user(1), fallback_store.get_user(1)

    primary_user, fallback_user = load_users()
    print(f"primary={primary_user}")  # => primary=redis:user:1
    print(f"fallback={fallback_user}")  # => fallback=memory:user:1


if __name__ == "__main__":
    main()
