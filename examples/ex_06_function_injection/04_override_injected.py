"""Focused example: caller override for injected parameters."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, provider_context


@dataclass(slots=True)
class User:
    email: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(User(email="container@example.com"))

    @provider_context.inject
    def handler(user: Injected[User]) -> str:
        return user.email

    default_value = handler()
    override_value = handler(user=User(email="override@example.com"))

    print(f"default_injected={default_value}")  # => default_injected=container@example.com
    print(f"override_injected={override_value}")  # => override_injected=override@example.com


if __name__ == "__main__":
    main()
