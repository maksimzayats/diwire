"""Focused example: ``auto_open_scope`` with scoped cleanup."""

from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Injected, Lifetime, Scope, provider_context


class Resource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"cleaned": False}

    def provide_resource() -> Generator[Resource, None, None]:
        try:
            yield Resource()
        finally:
            state["cleaned"] = True

    container.add_generator(
        provide_resource,
        provides=Resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @provider_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(resource: Injected[Resource]) -> Resource:
        return resource

    _ = handler()
    print(f"auto_scope_cleanup={state['cleaned']}")  # => auto_scope_cleanup=True


if __name__ == "__main__":
    main()
