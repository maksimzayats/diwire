"""Focused example: ``Injected[T]`` and public signature filtering."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from diwire import Container, Injected


@dataclass(slots=True)
class User:
    email: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(User(email="user@example.com"))

    @container.inject
    def handler(user_email: str, user: Injected[User], user_name: str) -> str:
        return f"{user_email}|{user_name}|{user.email}"

    signature = "('" + "','".join(inspect.signature(handler).parameters) + "')"
    print(f"signature={signature}")  # => signature=('user_email','user_name')


if __name__ == "__main__":
    main()
