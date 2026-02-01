"""Scoped service resolved outside scope (auto-register safety).

Demonstrates DIWireScopeMismatchError when:
- a service is registered only as SCOPED
- you try to resolve it outside the required scope

This prevents the container from silently auto-registering a second, unscoped instance.
"""

from dataclasses import dataclass

from diwire import Container, Lifetime
from diwire.exceptions import DIWireScopeMismatchError


@dataclass
class Session:
    active: bool = True


def main() -> None:
    container = Container(autoregister=True)
    container.register(Session, lifetime=Lifetime.SCOPED, scope="request")

    print("Resolving a SCOPED service outside its scope:\n")
    try:
        container.resolve(Session)
    except DIWireScopeMismatchError as e:
        print("DIWireScopeMismatchError caught!")
        print(f"  service: {e.service_key}")
        print(f"  registered_scope: {e.registered_scope}")
        print(f"  current_scope: {e.current_scope}")

    print("\nResolving inside the correct scope:")
    with container.enter_scope("request") as scope:
        session = scope.resolve(Session)
        print(f"  session.active={session.active}")


if __name__ == "__main__":
    main()

