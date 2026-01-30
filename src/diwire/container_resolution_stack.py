from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar

from diwire.service_key import ServiceKey

_thread_local = threading.local()

# Context variable for async resolution tracking
# Stores (task_id, stack) tuple to detect when stack needs cloning for new async tasks
_async_resolution_stack: ContextVar[tuple[int | None, list[ServiceKey]] | None] = ContextVar(
    "async_resolution_stack",
    default=None,
)


def _get_context_id() -> int | None:
    """Get an identifier for the current execution context.

    Returns the id of the current async task if running in an async context,
    or None if running in a sync context.
    """
    try:
        task = asyncio.current_task()
        return id(task) if task is not None else None
    except RuntimeError:
        return None


def _get_resolution_stack() -> list[ServiceKey]:
    """Get the current context's resolution stack.

    Uses threading.local for sync thread isolation and ContextVar for async task isolation.
    This ensures each thread and each async task gets its own independent resolution stack,
    which is required for correctness under free-threaded (no-GIL) Python.
    """
    current_task_id = _get_context_id()

    if current_task_id is not None:
        # Async path: use ContextVar for task isolation
        stored = _async_resolution_stack.get()
        if stored is None:
            stack: list[ServiceKey] = []
            _async_resolution_stack.set((current_task_id, stack))
            return stack

        owner_task_id, stack = stored

        # If we're in a different async task, clone the stack for isolation
        if owner_task_id != current_task_id:
            cloned_stack = list(stack)
            _async_resolution_stack.set((current_task_id, cloned_stack))
            return cloned_stack

        return stack

    # Sync path: use threading.local for thread isolation
    thread_stack: list[ServiceKey] | None = getattr(_thread_local, "resolution_stack", None)
    if thread_stack is None:
        thread_stack = []
        _thread_local.resolution_stack = thread_stack
    return thread_stack
