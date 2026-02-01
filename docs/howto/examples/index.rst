.. meta::
   :description: A step-by-step tutorial of runnable examples for diwire, from basics to scopes, async, and FastAPI integration.

Tutorial (runnable examples)
============================

All examples below are self-contained scripts.
You can:

- run most of them in your browser (click **Run** in the top-right of a code block)
- copy a block into a local ``.py`` file and run it with ``python``

The FastAPI examples are the main exception: they are not runnable in the browser.

Follow this path (easy -> hard)
-------------------------------

This tutorial is intentionally example-first. If you want the full mental model, use :doc:`../../core/index`
alongside the examples.

1. Basics (registration, lifetimes, constructor injection)
2. Scopes (SCOPED, generator cleanup, nested scopes)
3. Function injection (Injected marker)
4. Components (multiple implementations by name)
5. Patterns (request handlers, repositories, interfaces)
6. Async
7. FastAPI
8. Errors (what failures look like)

.. toctree::
   :maxdepth: 2

   basics
   scopes
   function-injection
   components
   patterns
   async
   fastapi
   errors
