"""Lifetimes: ``TRANSIENT`` and ``SCOPED``.

See how object identity changes across repeated resolves and scope boundaries,
including root-scoped ``SCOPED`` singleton behavior.
"""

from __future__ import annotations

from diwire import Container, Lifetime, Scope


class TransientService:
    pass


class SingletonService:
    pass


class ScopedService:
    pass


def main() -> None:
    container = Container()

    container.add_concrete(
        TransientService,
        provides=TransientService,
        lifetime=Lifetime.TRANSIENT,
    )
    transient_first = container.resolve(TransientService)
    transient_second = container.resolve(TransientService)
    print(f"transient_new={transient_first is not transient_second}")  # => transient_new=True

    container.add_concrete(
        SingletonService,
        provides=SingletonService,
        lifetime=Lifetime.SCOPED,
    )
    singleton_first = container.resolve(SingletonService)
    singleton_second = container.resolve(SingletonService)
    print(f"singleton_same={singleton_first is singleton_second}")  # => singleton_same=True

    container.add_concrete(
        ScopedService,
        provides=ScopedService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        scoped_first = request_scope.resolve(ScopedService)
        scoped_second = request_scope.resolve(ScopedService)

    with container.enter_scope() as request_scope:
        scoped_third = request_scope.resolve(ScopedService)

    print(f"scoped_same_within={scoped_first is scoped_second}")  # => scoped_same_within=True
    print(f"scoped_diff_across={scoped_first is not scoped_third}")  # => scoped_diff_across=True


if __name__ == "__main__":
    main()
