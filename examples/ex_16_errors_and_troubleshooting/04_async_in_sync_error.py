"""Focused example: ``DIWireAsyncDependencyInSyncContextError``."""

from __future__ import annotations

from diwire import Container
from diwire.exceptions import DIWireAsyncDependencyInSyncContextError


class AsyncDependency:
    pass


async def provide_async_dependency() -> AsyncDependency:
    return AsyncDependency()


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.register_factory(AsyncDependency, factory=provide_async_dependency)

    try:
        container.resolve(AsyncDependency)
    except DIWireAsyncDependencyInSyncContextError as error:
        error_name = type(error).__name__

    print(f"async_in_sync={error_name}")  # => async_in_sync=DIWireAsyncDependencyInSyncContextError


if __name__ == "__main__":
    main()
