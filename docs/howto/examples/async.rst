.. meta::
   :description: diwire async examples: aresolve() with async factories, async generator cleanup, async injected functions, async scoped injection, parallel resolution, and async errors.

Async
=====

Basic async factory
-------------------

Demonstrates how to register and resolve services with async factories.
Async factories are auto-detected (no special configuration needed).

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container, Lifetime


   class Database:
       def __init__(self, dsn: str) -> None:
           self.dsn = dsn
           self.connected = False

       async def connect(self) -> None:
           await asyncio.sleep(0.01)
           self.connected = True


   async def create_database() -> Database:
       db = Database("postgresql://localhost/mydb")
       await db.connect()
       return db


   async def main() -> None:
       container = Container()
       container.register(Database, factory=create_database, lifetime=Lifetime.SINGLETON)

       db = await container.aresolve(Database)
       print(f"connected={db.connected}")


   if __name__ == "__main__":
       asyncio.run(main())

Async generator cleanup
-----------------------

Demonstrates how async generators can be used for resource lifecycle management.
The cleanup code in the ``finally`` block runs automatically when the scope exits.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container, Lifetime


   class DatabaseSession:
       def __init__(self, session_id: str) -> None:
           self.session_id = session_id
           self.closed = False

       async def close(self) -> None:
           await asyncio.sleep(0.01)
           self.closed = True
           print(f"closed {self.session_id}")


   async def create_session():
       session = DatabaseSession("session-1")
       print(f"opened {session.session_id}")
       try:
           yield session
       finally:
           await session.close()


   async def main() -> None:
       container = Container()
       container.register(
           DatabaseSession,
           factory=create_session,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )

       async with container.enter_scope("request"):
           session1 = await container.aresolve(DatabaseSession)
           session2 = await container.aresolve(DatabaseSession)
           print(f"same instance: {session1 is session2}")


   if __name__ == "__main__":
       asyncio.run(main())

Async injected functions
------------------------

Demonstrates how to use ``Injected`` with async functions.
The resolved function becomes an ``AsyncInjectedFunction`` wrapper that resolves
dependencies on each call.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   import inspect
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class UserRepository:
       async def get_username(self, user_id: int) -> str:
           await asyncio.sleep(0.01)
           return f"user-{user_id}"


   class Logger:
       def info(self, message: str) -> None:
           print(f"[INFO] {message}")


   async def get_user_handler(
       user_id: int,
       repo: Annotated[UserRepository, Injected()],
       logger: Annotated[Logger, Injected()],
   ) -> dict[str, str]:
       logger.info(f"fetch user {user_id}")  # noqa: G004
       return {"user": await repo.get_username(user_id)}


   async def main() -> None:
       container = Container()
       container.register(UserRepository, lifetime=Lifetime.SINGLETON)
       container.register(Logger, lifetime=Lifetime.SINGLETON)

       handler = await container.aresolve(get_user_handler)
       print(f"wrapped: {type(handler)}")
       print(f"signature: {inspect.signature(handler)}")
       print(await handler(user_id=42))


   if __name__ == "__main__":
       asyncio.run(main())

Async scoped injection
----------------------

Demonstrates ``AsyncScopedInjected``: resolving an async function with
``scope="request"`` creates a new scope per invocation.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   from typing import Annotated

   from diwire import Container, Injected, Lifetime


   class RequestContext:
       _counter = 0

       def __init__(self) -> None:
           type(self)._counter += 1
           self.request_id = f"req-{type(self)._counter}"


   async def handler(
       payload: dict[str, str],
       ctx: Annotated[RequestContext, Injected()],
   ) -> dict[str, str]:
       await asyncio.sleep(0.01)
       return {"request_id": ctx.request_id, "payload": str(payload)}


   async def main() -> None:
       container = Container()
       container.register(
           RequestContext,
           lifetime=Lifetime.SCOPED,
           scope="request",
       )

       per_request = await container.aresolve(handler, scope="request")
       print(await per_request(payload={"n": "1"}))
       print(await per_request(payload={"n": "2"}))


   if __name__ == "__main__":
       asyncio.run(main())

Mixed sync/async + parallel resolution
--------------------------------------

Independent async dependencies are resolved in parallel via ``asyncio.gather()``.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio
   import time
   from dataclasses import dataclass

   from diwire import Container


   class DatabasePool:
       pass


   class CacheClient:
       pass


   class ExternalAPIClient:
       pass


   async def create_db_pool() -> DatabasePool:
       await asyncio.sleep(0.05)
       return DatabasePool()


   async def create_cache() -> CacheClient:
       await asyncio.sleep(0.05)
       return CacheClient()


   async def create_api_client() -> ExternalAPIClient:
       await asyncio.sleep(0.05)
       return ExternalAPIClient()


   @dataclass
   class App:
       db: DatabasePool
       cache: CacheClient
       api: ExternalAPIClient


   async def main() -> None:
       container = Container()
       container.register(DatabasePool, factory=create_db_pool)
       container.register(CacheClient, factory=create_cache)
       container.register(ExternalAPIClient, factory=create_api_client)
       container.register(App)

       start = time.perf_counter()
       app = await container.aresolve(App)
       elapsed = time.perf_counter() - start

       print(f"resolved in {elapsed:.3f}s")
       print(f"app.db={type(app.db).__name__}, app.cache={type(app.cache).__name__}, app.api={type(app.api).__name__}")


   if __name__ == "__main__":
       asyncio.run(main())

Async error handling
--------------------

``DIWireAsyncDependencyInSyncContextError``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Raised when a sync ``resolve()`` hits an async dependency.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container
   from diwire.exceptions import DIWireAsyncDependencyInSyncContextError


   class AsyncDatabase:
       pass


   async def create_async_db() -> AsyncDatabase:
       await asyncio.sleep(0.01)
       return AsyncDatabase()


   def main() -> None:
       container = Container()
       container.register(AsyncDatabase, factory=create_async_db)

       try:
           container.resolve(AsyncDatabase)
       except DIWireAsyncDependencyInSyncContextError as e:
           print(f"Caught: {type(e).__name__}")
           print(f"Message: {e}")


   if __name__ == "__main__":
       main()

``DIWireAsyncGeneratorFactoryWithoutScopeError``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Raised when an async generator factory is used without a scope for cleanup.

.. code-block:: python
   :class: diwire-example py-run

   import asyncio

   from diwire import Container, Lifetime
   from diwire.exceptions import DIWireAsyncGeneratorFactoryWithoutScopeError


   async def session_factory():
       yield "session"


   async def main() -> None:
       container = Container()
       container.register("Session", factory=session_factory, lifetime=Lifetime.TRANSIENT)

       try:
           await container.aresolve("Session")
       except DIWireAsyncGeneratorFactoryWithoutScopeError as e:
           print(f"Caught: {type(e).__name__}")
           print(f"Message: {e}")


   if __name__ == "__main__":
       asyncio.run(main())

Web frameworks
--------------

For end-to-end web-framework integrations, see :doc:`fastapi`.

Read more
---------

- :doc:`../../core/async`
- :doc:`../../core/scopes`
