.. meta::
   :description: diwire basics examples: registration methods, lifetimes, constructor injection, decorator registration, open generics, and compilation.

Basics
======

Registration methods
--------------------

Demonstrates three ways to register services:

#. Class registration - container creates instances
#. Factory registration - custom function creates instances
#. Instance registration - pre-created singleton

Class registration
^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container


   class Logger:
       def log(self, message: str) -> None:
           print(f"[LOG] {message}")


   def main() -> None:
       container = Container(autoregister=False)
       container.register(Logger)

       logger = container.resolve(Logger)
       logger.log("Hello from registered class!")


   if __name__ == "__main__":
       main()

Factory registration
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container


   @dataclass
   class Database:
       host: str
       port: int


   def create_database() -> Database:
       # Use a factory when you need custom instantiation logic.
       return Database(host="localhost", port=5432)


   def main() -> None:
       container = Container(autoregister=False)
       container.register(Database, factory=create_database)

       db = container.resolve(Database)
       print(f"Database: {db.host}:{db.port}")


   if __name__ == "__main__":
       main()

Instance registration
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container


   class Cache:
       def __init__(self) -> None:
           self.data: dict[str, str] = {}


   def main() -> None:
       container = Container(autoregister=False)

       # Instance registrations are always singletons.
       cache_instance = Cache()
       cache_instance.data["key"] = "value"
       container.register(Cache, instance=cache_instance)

       resolved_cache = container.resolve(Cache)
       print(f"Cache data: {resolved_cache.data}")
       print(f"Same instance: {resolved_cache is cache_instance}")


   if __name__ == "__main__":
       main()

Lifetimes (TRANSIENT vs SINGLETON)
----------------------------------

Demonstrates the difference between:

- ``TRANSIENT``: new instance on every resolve
- ``SINGLETON``: same instance for entire container lifetime

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container, Lifetime


   class TransientService:
       """Created fresh on each resolution."""


   class SingletonService:
       """Shared across all resolutions."""


   def main() -> None:
       container = Container(autoregister=False)

       # TRANSIENT: new instance every time
       container.register(TransientService, lifetime=Lifetime.TRANSIENT)

       t1 = container.resolve(TransientService)
       t2 = container.resolve(TransientService)
       t3 = container.resolve(TransientService)

       print("TRANSIENT instances:")
       print(f"  t1 id: {id(t1)}")
       print(f"  t2 id: {id(t2)}")
       print(f"  t3 id: {id(t3)}")
       print(f"  All different: {t1 is not t2 is not t3}")

       # SINGLETON: same instance always
       container.register(SingletonService, lifetime=Lifetime.SINGLETON)

       s1 = container.resolve(SingletonService)
       s2 = container.resolve(SingletonService)
       s3 = container.resolve(SingletonService)

       print("\nSINGLETON instances:")
       print(f"  s1 id: {id(s1)}")
       print(f"  s2 id: {id(s2)}")
       print(f"  s3 id: {id(s3)}")
       print(f"  All same: {s1 is s2 is s3}")


   if __name__ == "__main__":
       main()

Constructor injection (auto-wiring)
-----------------------------------

Demonstrates automatic dependency resolution through constructor parameters.
The container analyzes type hints and injects dependencies automatically.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Any

   from diwire import Container


   @dataclass
   class Config:
       """Application configuration."""

       database_url: str = "postgresql://localhost/app"
       debug: bool = True


   @dataclass
   class Database:
       """Database connection that depends on Config."""

       config: Config

       def query(self, sql: str, **kwargs: Any) -> str:
           return f"Executing on {self.config.database_url}: {sql.format(**kwargs)}"


   @dataclass
   class UserRepository:
       """Repository that depends on Database."""

       db: Database

       def find_user(self, user_id: int) -> str:
           return self.db.query("SELECT * FROM users WHERE id = {user_id}", user_id=user_id)


   @dataclass
   class UserService:
       """Service that depends on UserRepository."""

       repo: UserRepository

       def get_user_info(self, user_id: int) -> str:
           return f"User info: {self.repo.find_user(user_id)}"


   def main() -> None:
       container = Container()

       # Register Config with a specific instance
       container.register(Config, instance=Config(database_url="postgresql://prod/app"))

       # Resolve UserService - container automatically resolves entire chain:
       # UserService -> UserRepository -> Database -> Config
       service = container.resolve(UserService)

       result = service.get_user_info(42)
       print(result)

       # The entire dependency chain was resolved:
       print("\nDependency chain resolved:")
       print(f"  UserService has repo: {service.repo}")
       print(f"  UserRepository has db: {service.repo.db}")
       print(f"  Database has config: {service.repo.db.config}")


   if __name__ == "__main__":
       main()

Decorator registration
----------------------

``@container.register`` works as a decorator for:

- classes (bare decorator or with explicit lifetime/scope)
- factory functions (return type inferred from annotations)
- interface / protocol bindings (``@container.register(Protocol, ...)``)

More scoped patterns and cleanup are in :doc:`scopes`.
Async factories and async generator cleanup are in :doc:`async`.
``container_context`` is covered in :doc:`/core/container-context` and :doc:`patterns`.

Class decorators
^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from diwire import Container, Lifetime

   container = Container(autoregister=False)


   @container.register
   class Config:
       def __init__(self) -> None:
           self.debug = True


   @container.register(lifetime=Lifetime.SINGLETON)
   class Logger:
       def log(self, message: str) -> None:
           print(f"[LOG] {message}")


   def main() -> None:
       cfg = container.resolve(Config)
       print(f"Config.debug={cfg.debug}")

       logger1 = container.resolve(Logger)
       logger2 = container.resolve(Logger)
       logger1.log(f"Logger is singleton: {logger1 is logger2}")


   if __name__ == "__main__":
       main()

Factory function decorators
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container

   container = Container(autoregister=False)


   @dataclass
   class Cache:
       data: dict[str, str]


   @container.register
   def create_cache() -> Cache:
       # The key is inferred from the return annotation.
       return Cache(data={"initialized": "true"})


   def main() -> None:
       cache = container.resolve(Cache)
       print(cache)


   if __name__ == "__main__":
       main()

Factory decorators with injected dependencies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container

   container = Container(autoregister=False)


   @dataclass
   class Settings:
       env: str


   @dataclass
   class Service:
       settings: Settings


   container.register(Settings, instance=Settings(env="dev"))


   @container.register
   def create_service(settings: Settings) -> Service:
       # Factory params are injected from type hints.
       return Service(settings=settings)


   def main() -> None:
       service = container.resolve(Service)
       print(f"Service.settings.env={service.settings.env}")


   if __name__ == "__main__":
       main()

Protocol/interface binding
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python
   :class: diwire-example py-run

   from typing import Protocol

   from diwire import Container, Lifetime


   class Database(Protocol):
       def query(self, sql: str) -> str: ...


   container = Container(autoregister=False)


   @container.register(Database, lifetime=Lifetime.SINGLETON)
   class PostgresDatabase:
       def query(self, sql: str) -> str:
           return f"[Postgres] {sql}"


   def main() -> None:
       db = container.resolve(Database)
       print(db.query("SELECT 1"))


   if __name__ == "__main__":
       main()

Open generics
-------------

Open generics let you register a *single* factory for a generic type (``Box[T]``) and resolve
it for any concrete type argument (``Box[int]``, ``Box[str]``, ...).

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Generic, TypeVar

   from diwire import Container

   T = TypeVar("T")


   @dataclass
   class Box(Generic[T]):
       value: str


   container = Container()

   @container.register(Box[T])
   def create_box(type_arg: type[T]) -> Box[T]:
       return Box(value=f"Box[{type_arg.__name__}]")


   print(container.resolve(Box[int]))
   print(container.resolve(Box[str]))

TypeVar bounds validation
^^^^^^^^^^^^^^^^^^^^^^^^^

diwire validates TypeVar bounds/constraints at runtime.

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass
   from typing import Generic, TypeVar

   from diwire import Container
   from diwire.exceptions import DIWireInvalidGenericTypeArgumentError


   class Model:
       pass


   class User(Model):
       pass


   M = TypeVar("M", bound=Model)


   @dataclass
   class ModelBox(Generic[M]):
       model: M


   container = Container()

   @container.register(ModelBox[M])
   def create_model_box(model_cls: type[M]) -> ModelBox[M]:
       return ModelBox(model=model_cls())


   print(container.resolve(ModelBox[User]))
   try:
       container.resolve(ModelBox[str])
   except DIWireInvalidGenericTypeArgumentError as e:
       print(f"Caught: {type(e).__name__}")
       print(f"Message: {e}")

Compilation
-----------

Demonstrates:

- manual compilation via ``container.compile()``
- disabling auto-compilation via ``Container(auto_compile=False)``

.. code-block:: python
   :class: diwire-example py-run

   from dataclasses import dataclass

   from diwire import Container, Lifetime


   @dataclass
   class ServiceA:
       value: str = "A"


   @dataclass
   class ServiceB:
       a: ServiceA


   def main() -> None:
       # Turn off auto-compilation so we can show the explicit call.
       container = Container(auto_compile=False)

       container.register(ServiceA, lifetime=Lifetime.SINGLETON)
       container.register(ServiceB, lifetime=Lifetime.TRANSIENT)

       # Works before compilation (reflection-based resolution).
       b1 = container.resolve(ServiceB)
       print(f"Before compile(): b1.a.value={b1.a.value!r}")

       # Precompute the dependency graph for maximum throughput.
       container.compile()

       b2 = container.resolve(ServiceB)
       print(f"After compile():  b2.a.value={b2.a.value!r}")

       # Transient behavior is unchanged: new ServiceB each time.
       print(f"Transient preserved: {b1 is not b2}")

       # Singleton behavior is unchanged: same ServiceA.
       print(f"Singleton preserved: {b1.a is b2.a}")


   if __name__ == "__main__":
       main()

Read more
---------

- :doc:`../../core/container`
- :doc:`../../core/registration`
- :doc:`../../core/lifetimes`
- :doc:`../../core/open-generics`
- :doc:`../../core/compilation`
