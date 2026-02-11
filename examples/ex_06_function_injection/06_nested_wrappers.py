"""Focused example: nested injected wrappers share one active resolver."""

from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, Lifetime, Scope


class RequestDependency:
    pass


@dataclass(slots=True)
class InnerService:
    dependency: RequestDependency


@dataclass(slots=True)
class OuterService:
    inner: InnerService
    dependency: RequestDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    def build_inner(dependency: Injected[RequestDependency]) -> InnerService:
        return InnerService(dependency=dependency)

    @container.inject
    def build_outer(
        inner: Injected[InnerService],
        dependency: Injected[RequestDependency],
    ) -> OuterService:
        return OuterService(inner=inner, dependency=dependency)

    container.add_factory(
        build_inner,
        provides=InnerService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_outer,
        provides=OuterService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(OuterService)

    print(
        f"nested_scope_identity={resolved.inner.dependency is resolved.dependency}",
    )  # => nested_scope_identity=True


if __name__ == "__main__":
    main()
