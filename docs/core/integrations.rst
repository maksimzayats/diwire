.. meta::
   :description: Integrations and compatibility notes for diwire: dataclasses, pydantic, attrs, msgspec, pydantic-settings BaseSettings auto-registration, and an optional pytest plugin.

Integrations
============

diwire works best with libraries that expose dependencies via a generated ``__init__`` signature and type hints.

Tested integrations
-------------------

These work out of the box (no adapters required):

- ``dataclasses`` (stdlib)
- Pydantic ``BaseModel`` and ``@pydantic.dataclasses.dataclass``
- ``attrs`` (``@attrs.define``)
- ``msgspec`` (``msgspec.Struct``)

pydantic-settings (BaseSettings)
--------------------------------

If you use ``pydantic-settings``, diwire includes a small integration:

- subclasses of ``pydantic_settings.BaseSettings`` are auto-registered as **singletons**
- the default factory is ``cls()`` (so values come from environment/.env, depending on your settings config)

Example:

.. code-block:: python

   from pydantic_settings import BaseSettings

   from diwire import Container


   class Settings(BaseSettings):
       database_url: str


   container = Container()
   settings = container.resolve(Settings)  # auto-registered singleton

pytest
------

diwire includes an optional pytest plugin that can resolve parameters annotated as
``Annotated[T, Injected()]`` directly in test functions.

See :doc:`/howto/testing/pytest`.
