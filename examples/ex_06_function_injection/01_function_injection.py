"""Function injection from basic marker usage to nested wrapper behavior.

This topic demonstrates:

1. ``Injected[T]`` marker semantics and signature filtering.
2. ``@resolver_context.inject`` behavior with caller overrides.
3. ``auto_open_scope`` cleanup for scoped generator resources.
4. Nested injected wrappers as providers sharing the same active resolver.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator
from dataclasses import dataclass

from diwire import Container, Injected, Lifetime, Scope, resolver_context


@dataclass(slots=True)
class User:
    email: str
    name: str


class RequestScopedResource:
    pass


class RequestDependency:
    pass


@dataclass(slots=True)
class NestedInnerService:
    dependency: RequestDependency


@dataclass(slots=True)
class NestedOuterService:
    inner: NestedInnerService
    dependency: RequestDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(
        User(email="injected@example.com", name="Injected"),
        provides=User,
    )

    @resolver_context.inject
    def render_user(
        user_email: str,
        user: Injected[User],
        user_name: str,
    ) -> str:
        return f"{user_email}|{user_name}|{user.email}"

    signature = "('" + "','".join(inspect.signature(render_user).parameters) + "')"
    print(f"signature={signature}")  # => signature=('user_email','user_name')

    injected_result = render_user("contact@example.com", user_name="Alex")
    print(
        f"injected_call_ok={injected_result == 'contact@example.com|Alex|injected@example.com'}",
    )  # => injected_call_ok=True

    overridden_user = User(email="override@example.com", name="Override")
    override_result = render_user(
        "contact@example.com",
        user_name="Alex",
        user=overridden_user,
    )
    print(
        f"override_ok={override_result == 'contact@example.com|Alex|override@example.com'}",
    )  # => override_ok=True

    cleanup_state = {"cleaned": False}

    def provide_scoped_resource() -> Generator[RequestScopedResource, None, None]:
        try:
            yield RequestScopedResource()
        finally:
            cleanup_state["cleaned"] = True

    container.add_generator(
        provide_scoped_resource,
        provides=RequestScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def use_scoped_resource(resource: Injected[RequestScopedResource]) -> RequestScopedResource:
        return resource

    _ = use_scoped_resource()
    print(f"auto_scope_cleanup={cleanup_state['cleaned']}")  # => auto_scope_cleanup=True

    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @resolver_context.inject
    def build_inner(dependency: Injected[RequestDependency]) -> NestedInnerService:
        return NestedInnerService(dependency=dependency)

    @resolver_context.inject
    def build_outer(
        inner: Injected[NestedInnerService],
        dependency: Injected[RequestDependency],
    ) -> NestedOuterService:
        return NestedOuterService(inner=inner, dependency=dependency)

    container.add_factory(
        build_inner,
        provides=NestedInnerService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_outer,
        provides=NestedOuterService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        nested = request_scope.resolve(NestedOuterService)

    print(
        f"nested_scope_identity={nested.inner.dependency is nested.dependency}",
    )  # => nested_scope_identity=True


if __name__ == "__main__":
    main()
