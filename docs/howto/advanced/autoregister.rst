.. meta::
   :description: Tune diwire auto-registration using strict Container and explicit AutoregisterContainer.

Auto-registration tuning
========================

Auto-registration enables the “just write types, then resolve the root” experience.

Strict mode (disable auto-registration)
---------------------------------------

Use :class:`diwire.Container` when you want your app to fail fast if anything is missing:

.. code-block:: python

   from diwire import Container

   container = Container()

In strict mode, resolving an unregistered dependency raises
:class:`diwire.exceptions.DIWireDependencyNotRegisteredError`.

Opt-in autoregistration
-----------------------

Use :class:`diwire.AutoregisterContainer` for explicit auto-wiring:

.. code-block:: python

   from diwire import AutoregisterContainer

   container = AutoregisterContainer()

Concrete types vs dependencies
------------------------------

- ``AutoregisterContainer`` always enables unknown *resolved* concrete class autoregistration.
- ``AutoregisterContainer(autoregister_dependencies=False)`` disables registration-time dependency autoregistration
  while keeping resolve-time concrete autoregistration enabled.

Pydantic settings auto-registration
-----------------------------------

If ``pydantic-settings`` is installed, subclasses of ``BaseSettings`` are auto-registered as
root-scoped ``Lifetime.SCOPED`` values (singleton behavior) via a no-argument factory.

See :doc:`../../core/integrations` and :doc:`../examples/pydantic-settings`.

Scope-safety
------------

If a type has any scoped registration, resolving it outside the correct scope raises
:class:`diwire.exceptions.DIWireScopeMismatchError` instead of silently creating an unscoped instance.

Runnable example: :doc:`../examples/scopes`.
