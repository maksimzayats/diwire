"""Async scoped function injection.

Demonstrates AsyncScopedInjected - an async function wrapper that
creates a new scope for each invocation. This ensures scoped dependencies
are properly isolated and cleaned up per call.
"""

import asyncio
from typing import Annotated

from diwire import Container, Injected, Lifetime


class RequestContext:
    """Per-request context with unique ID."""

    _counter = 0

    def __init__(self):
        RequestContext._counter += 1
        self.request_id = f"req-{RequestContext._counter}"
        print(f"    Created {self.request_id}")

    def __repr__(self) -> str:
        return f"RequestContext({self.request_id})"


class DatabaseTransaction:
    """Simulated database transaction tied to request scope."""

    def __init__(self, context: RequestContext):
        self.context = context
        self.committed = False
        self.rolled_back = False
        print(f"    Created transaction for {context.request_id}")


# Async generator for transaction with cleanup
async def create_transaction(context: RequestContext):
    """Creates a transaction that auto-commits or rolls back."""
    tx = DatabaseTransaction(context)
    try:
        yield tx
        # If we get here without exception, commit
        print(f"    Committing transaction for {context.request_id}")
        tx.committed = True
    except Exception:
        print(f"    Rolling back transaction for {context.request_id}")
        tx.rolled_back = True
        raise


# Request handler - gets scoped dependencies
async def handle_request(
    context: Annotated[RequestContext, Injected()],
    transaction: Annotated[DatabaseTransaction, Injected()],
    data: dict,
) -> dict:
    """Handler that uses scoped dependencies.

    Each call gets its own RequestContext and DatabaseTransaction.
    """
    print(f"    Processing request {context.request_id} with data: {data}")
    await asyncio.sleep(0.01)  # Simulate async work
    return {
        "request_id": context.request_id,
        "status": "success",
        "data": data,
    }


async def main() -> None:
    container = Container()

    # Register scoped dependencies
    container.register(
        RequestContext,
        lifetime=Lifetime.SCOPED,
        scope="request",
    )
    container.register(
        DatabaseTransaction,
        factory=create_transaction,
        lifetime=Lifetime.SCOPED,
        scope="request",
    )

    # Resolve function with scoped deps - returns AsyncScopedInjected
    handler = await container.aresolve(handle_request)
    print(f"Handler type: {type(handler)}")

    # Each call creates a new scope with fresh dependencies
    print("\n--- First request ---")
    result1 = await handler(data={"action": "create", "item": "foo"})
    print(f"Result: {result1}")

    print("\n--- Second request ---")
    result2 = await handler(data={"action": "update", "item": "bar"})
    print(f"Result: {result2}")

    # Notice: different request IDs for each call
    print(f"\nDifferent request IDs: {result1['request_id']} vs {result2['request_id']}")

    # Concurrent requests each get their own scope
    print("\n--- Concurrent requests ---")

    async def make_request(n: int) -> dict:
        return await handler(data={"request_number": n})

    results = await asyncio.gather(
        make_request(1),
        make_request(2),
        make_request(3),
    )

    print("\nConcurrent results:")
    for r in results:
        print(f"  {r['request_id']}: {r['data']}")


if __name__ == "__main__":
    asyncio.run(main())
