from __future__ import annotations

import asyncio
from contextvars import ContextVar

from diwire.service_key import ServiceKey

# Context variable for resolution tracking (works with both threads and async tasks)
# Stores (task_id, stack) tuple to detect when stack needs cloning for new async tasks
_resolution_stack: ContextVar[tuple[int | None, list[ServiceKey]] | None] = ContextVar(
    "resolution_stack",
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

    When called from a different async task than the one that created the stack,
    returns a cloned copy to ensure task isolation during parallel resolution.
    """
    current_task_id = _get_context_id()
    stored = _resolution_stack.get()

    if stored is None:
        # Create a new list for this context
        stack: list[ServiceKey] = []
        _resolution_stack.set((current_task_id, stack))
        return stack

    owner_task_id, stack = stored

    # If we're in a different async task, clone the stack for isolation
    if current_task_id is not None and owner_task_id != current_task_id:
        cloned_stack = list(stack)
        _resolution_stack.set((current_task_id, cloned_stack))
        return cloned_stack

    return stack
