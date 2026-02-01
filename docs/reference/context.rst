container_context
=================

``container_context`` is an instance of an internal proxy class that forwards calls to the "current" container stored
in ``contextvars``.

.. autoclass:: diwire.container_context._ContainerContextProxy
   :members: set_current, get_current, reset, register, resolve, aresolve, close, aclose, close_scope, aclose_scope
   :member-order: bysource

