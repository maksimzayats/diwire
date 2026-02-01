.. meta::
   :description: Integrate diwire with web frameworks: FastAPI today, and patterns for Starlette, Flask, Django, aiohttp, and more.

Web frameworks
==============

diwire is intentionally framework-agnostic.

The common pattern is:

1. Build a :class:`diwire.Container` at app startup.
2. Create a request/job scope per incoming request.
3. Register request-specific objects (like the current request) via factories/contextvars.
4. Use function injection (``Injected()``) or ``container_context`` to keep handlers clean.

.. toctree::
   :maxdepth: 1

   fastapi
   starlette
   flask
   django

