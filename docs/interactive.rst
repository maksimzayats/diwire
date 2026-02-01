Interactive code blocks
=======================

Any Python code block marked with ``:class: py-run`` includes action buttons in
the top-right corner:

- **Run** (play icon) — executes the code in the browser using Pyodide and
  shows output below the block.
- **Edit** (pencil icon) — toggles the block into an editable state so you can
  modify the code before running it.
- **Copy** (clipboard icon, from sphinx-copybutton) — copies the code to your
  clipboard.

.. code-block:: python
   :class: py-run

   from dataclasses import dataclass
   from diwire import Container, Lifetime


   @dataclass
   class Database:
       host: str = "localhost"


   @dataclass
   class UserRepository:
       db: Database


   @dataclass
   class UserService:
       repo: UserRepository


   container = Container(autoregister_default_lifetime=Lifetime.TRANSIENT)
   service = container.resolve(UserService)
   print(f"Resolved host: {service.repo.db.host}")
