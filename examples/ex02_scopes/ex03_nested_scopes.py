"""Nested Scopes in DIWire.

Demonstrates hierarchical scope nesting where child scopes
can access services from parent scopes.
"""

from enum import Enum

from diwire import Container, Lifetime


class Scope(str, Enum):
    """Application scope definitions."""

    REQUEST = "request"
    HANDLER = "handler"


class RequestContext:
    """Request-level context, shared within a request."""

    def __init__(self) -> None:
        self.request_id = id(self)


class HandlerContext:
    """Handler-level context, specific to each handler invocation."""

    def __init__(self) -> None:
        self.handler_id = id(self)


def main() -> None:
    container = Container()

    container.register(
        RequestContext,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.register(
        HandlerContext,
        lifetime=Lifetime.SCOPED,
        scope=Scope.HANDLER,
    )

    print("Nested scopes demonstration:\n")

    with container.enter_scope(Scope.REQUEST) as request_scope:
        request_ctx = request_scope.resolve(RequestContext)
        print(f"Request scope - RequestContext id: {request_ctx.request_id}")

        # Create nested handler scopes
        with request_scope.enter_scope(Scope.HANDLER) as handler_scope1:
            handler_ctx1 = handler_scope1.resolve(HandlerContext)
            # Parent's RequestContext is accessible from child
            inherited_request_ctx = handler_scope1.resolve(RequestContext)

            print("\n  Handler scope 1:")
            print(f"    HandlerContext id: {handler_ctx1.handler_id}")
            print(f"    RequestContext id: {inherited_request_ctx.request_id}")
            print(f"    Same request context: {inherited_request_ctx is request_ctx}")

        with request_scope.enter_scope(Scope.HANDLER) as handler_scope2:
            handler_ctx2 = handler_scope2.resolve(HandlerContext)
            inherited_request_ctx2 = handler_scope2.resolve(RequestContext)

            print("\n  Handler scope 2:")
            print(f"    HandlerContext id: {handler_ctx2.handler_id}")
            print(f"    RequestContext id: {inherited_request_ctx2.request_id}")
            print(f"    Same request context: {inherited_request_ctx2 is request_ctx}")
            print(f"    Different handler context: {handler_ctx2 is not handler_ctx1}")


if __name__ == "__main__":
    main()
