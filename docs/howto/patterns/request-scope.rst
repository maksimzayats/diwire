.. meta::
   :description: How to use request scopes with diwire: register SCOPED services, enter a scope per request, and inject request-local dependencies safely.

Request scope
=============

A "request scope" is the most common unit of work for DI in web apps.

The pattern
-----------

1. Pick a scope name (commonly ``"request"``).
2. Register request-local services with ``lifetime=Lifetime.SCOPED`` and ``scope="request"``.
3. Enter the scope for each request and resolve your handler/service graph inside it.

Example (runnable)
------------------

See the full script:

See the runnable script in :doc:`../examples/patterns` (HTTP request handler pattern section).

Notes
-----

- Scoped services are reused within a single request, but *not* across requests.
- Use generator/async-generator factories for cleanup (DB sessions, connections). See :doc:`resources`.
