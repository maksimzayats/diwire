.. meta::
   :description: Tune diwire auto-registration: enable/disable, adjust ignored types, add custom registration factories, and understand scope-safety behavior.

Auto-registration tuning
========================

Auto-registration is what enables "just write types, then resolve the root".
It's enabled by default.

Disable auto-registration (strict mode)
---------------------------------------

.. code-block:: python

   from diwire import Container

   container = Container(autoregister=False)

Strict mode is useful when you want your app to fail fast if anything is missing.

Ignored types
-------------

By default, diwire ignores common primitives/collections during auto-wiring (``int``, ``str``, ``dict``, ...).
If a constructor parameter is ignored and has no default value, you'll get a missing dependency error.

You can customize the ignore set:

.. code-block:: python

   from diwire import Container

   container = Container(autoregister_ignores={str, int})

Custom auto-registration factories
----------------------------------

Sometimes a base class should be auto-registered in a special way.
diwire supports this via ``autoregister_registration_factories``.

One built-in example is ``pydantic-settings``: subclasses of ``BaseSettings`` are auto-registered as singletons.
See :doc:`../../core/integrations`.

Scope-safety
------------

If a type has *any* scoped registration, resolving it outside the correct scope raises
:class:`diwire.exceptions.DIWireScopeMismatchError` instead of silently auto-registering a second, unscoped instance.
This is an intentional safety feature.

Runnable example:

See the runnable script in :doc:`../examples/errors` (Scoped resolved outside scope section).
