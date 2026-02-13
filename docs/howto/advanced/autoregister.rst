.. meta::
   :description: Tune diwire auto-registration: strict mode flags, dependency auto-registration during registration, and scope-safety behavior.

Auto-registration tuning
========================

Auto-registration enables the “just write types, then resolve the root” experience.

Strict mode (disable auto-registration)
---------------------------------------

Disable auto-registration when you want your app to fail fast if anything is missing:

.. code-block:: python

   from diwire import Container

   container = Container()

In strict mode, resolving an unregistered dependency raises
:class:`diwire.exceptions.DIWireDependencyNotRegisteredError`.

Autoregister concrete types vs dependencies
-------------------------------------------

- ``missing_policy`` controls resolve-time behavior for unknown concrete classes.
- ``dependency_registration_policy`` controls container-level defaults for whether provider dependencies are
  automatically registered as concrete types at **registration time**.
- ``dependency_registration_policy`` is the call-level override on ``add``, ``add_factory``,
  ``add_generator``, ``add_context_manager``, and ``resolver_context.inject``.

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
