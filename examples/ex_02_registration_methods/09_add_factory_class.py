"""Focused example: ``add_factory_class`` for reusable provider state."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected


@dataclass(frozen=True, slots=True)
class Settings:
    endpoint: str


@dataclass(frozen=True, slots=True)
class Client:
    endpoint: str


@dataclass(kw_only=True)
class ClientFactory:
    settings: Injected[Settings]

    def __call__(self) -> Client:
        return Client(endpoint=self.settings.endpoint)


def main() -> None:
    container = Container()
    container.add_instance(Settings(endpoint="https://api.example.test"))
    container.add_factory_class(ClientFactory, provides=Client)

    client = container.resolve(Client)
    print(
        f"factory_class_endpoint={client.endpoint}"
    )  # => factory_class_endpoint=https://api.example.test


if __name__ == "__main__":
    main()
