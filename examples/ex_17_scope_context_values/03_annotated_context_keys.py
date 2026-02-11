"""Annotated tokens can be used as scope context keys."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from diwire import Component, Container, FromContext, Lifetime, Scope

ReplicaNumber: TypeAlias = Annotated[int, Component("replica")]


class ReplicaConsumer:
    def __init__(self, value: int) -> None:
        self.value = value


def build_consumer(value: FromContext[ReplicaNumber]) -> ReplicaConsumer:
    return ReplicaConsumer(value=value)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.register_factory(
        ReplicaConsumer,
        factory=build_consumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope(Scope.REQUEST, context={ReplicaNumber: 42}) as request_scope:
        resolved = request_scope.resolve(ReplicaConsumer)
        direct = request_scope.resolve(FromContext[ReplicaNumber])

    print(f"consumer_value={resolved.value}")
    print(f"direct_value={direct}")


if __name__ == "__main__":
    main()
