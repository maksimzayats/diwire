"""Scopes and cleanup behavior across transitions and lifetimes.

This module covers:

1. Default ``enter_scope()`` transition behavior (skippable scopes).
2. Explicit ``enter_scope(Scope.SESSION)`` and ``enter_scope(Scope.ACTION)``.
3. ``DIWireScopeMismatchError`` when resolving a scoped dependency from root.
4. Scoped cleanup timing (on scope exit).
5. Singleton cleanup timing (on ``container.close()``).
"""

from __future__ import annotations

from collections.abc import Generator

from diwire import Container, DIWireScopeMismatchError, Lifetime, Scope


class RequestScopedDependency:
    pass


class ScopedResource:
    pass


class SingletonResource:
    pass


def _resolver_scope_name(resolver: object) -> str:
    class_name = type(resolver).__name__
    return class_name.removeprefix("_").removesuffix("Resolver").upper()


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_concrete(
        RequestScopedDependency,
        provides=RequestScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as default_scope:
        default_scope_name = _resolver_scope_name(default_scope)
    print(f"enter_scope_default={default_scope_name}")  # => enter_scope_default=REQUEST

    with container.enter_scope(Scope.ACTION) as action_scope:
        resolved_in_action = action_scope.resolve(RequestScopedDependency)
    print(
        f"action_scope_can_resolve_request_scoped={isinstance(resolved_in_action, RequestScopedDependency)}",
    )  # => action_scope_can_resolve_request_scoped=True

    try:
        container.resolve(RequestScopedDependency)
    except DIWireScopeMismatchError as error:
        mismatch_error_name = type(error).__name__
    print(
        f"scope_mismatch_error={mismatch_error_name}",
    )  # => scope_mismatch_error=DIWireScopeMismatchError

    scoped_state = {"opened": 0, "closed": 0}

    def provide_scoped_resource() -> Generator[ScopedResource, None, None]:
        scoped_state["opened"] += 1
        try:
            yield ScopedResource()
        finally:
            scoped_state["closed"] += 1

    container.add_generator(
        provide_scoped_resource,
        provides=ScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(ScopedResource)
        closed_while_scope_open = scoped_state["closed"]

    scoped_cleanup_after_exit = closed_while_scope_open == 0 and scoped_state["closed"] == 1
    print(
        f"scoped_cleanup_after_exit={scoped_cleanup_after_exit}",
    )  # => scoped_cleanup_after_exit=True

    singleton_state = {"opened": 0, "closed": 0}

    def provide_singleton_resource() -> Generator[SingletonResource, None, None]:
        singleton_state["opened"] += 1
        try:
            yield SingletonResource()
        finally:
            singleton_state["closed"] += 1

    container.add_generator(
        provide_singleton_resource,
        provides=SingletonResource,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )
    _ = container.resolve(SingletonResource)
    closed_before_close = singleton_state["closed"]
    container.close()
    singleton_cleanup_on_close = closed_before_close == 0 and singleton_state["closed"] == 1
    print(
        f"singleton_cleanup_on_close={singleton_cleanup_on_close}",
    )  # => singleton_cleanup_on_close=True


if __name__ == "__main__":
    main()
