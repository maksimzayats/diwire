.. meta::
   :description: Open generics in diwire: register factories for generic types (e.g. Repo[T]) and resolve closed generics with runtime validation of TypeVar bounds/constraints.

Open generics
=============

Open generics let you register a *single* factory for a generic type, and then resolve it for any concrete type
argument:

- register ``Repository[T]`` once
- resolve ``Repository[User]``, ``Repository[Order]``, ...

diwire also validates TypeVar bounds/constraints at runtime.

Example
-------

See the runnable script in :doc:`/howto/examples/basics` (Open generics section).

How it works
------------

- You register an **open** generic key that contains one or more TypeVars (for example ``AnyBox[T]``).
- When you resolve a **closed** generic (for example ``AnyBox[int]``), diwire:

  1. matches the closed generic to the registered open generic
  2. validates the concrete type arguments against TypeVar bounds/constraints
  3. calls your factory and passes the concrete type argument(s) (for example ``type[int]``) as parameters
