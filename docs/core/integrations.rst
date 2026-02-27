.. meta::
   :description: Integrations and compatibility notes for diwire: supported constructor/field extraction, pydantic-settings, and the optional pytest plugin.

Integrations
============

diwire works best with libraries that expose dependencies via a generated ``__init__`` signature and type hints.

Supported constructor/field extraction
--------------------------------------

These work out of the box (no adapters required):

- ``dataclasses`` (stdlib)
- ``typing.NamedTuple``
- ``attrs`` (``@attrs.define``)
- Pydantic ``BaseModel`` (v2)
- ``msgspec.Struct``

Runnable example: :doc:`/howto/examples/supported-frameworks`.

pydantic-settings
-----------------

If you use ``pydantic-settings``, diwire includes a small integration:

- subclasses of ``pydantic_settings.BaseSettings`` are auto-registered as root-scoped
  ``Lifetime.SCOPED`` values (singleton behavior)
- the default factory is ``cls()``

Runnable example: :doc:`/howto/examples/pydantic-settings`.

pytest plugin
-------------

diwire ships with an optional pytest plugin that can resolve parameters annotated as ``Injected[T]`` directly in test
functions from a root test container.

Runnable example: :doc:`/howto/examples/pytest-plugin`.

Web frameworks (FastAPI + aiohttp + Sanic)
------------------------------------------

diwire includes dedicated middleware/context integrations for FastAPI, aiohttp, and Sanic.
Use ``@resolver_context.inject(scope=Scope.REQUEST)`` on handlers/endpoints and install the
framework-specific request context middleware plus ``add_request_context(container)``.

See :doc:`/howto/web/fastapi`, :doc:`/howto/web/aiohttp`, :doc:`/howto/web/sanic`, and the
runnable script :doc:`/howto/examples/fastapi`.
