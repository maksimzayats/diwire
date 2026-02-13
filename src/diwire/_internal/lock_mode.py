from __future__ import annotations

from enum import Enum


class LockMode(Enum):
    """Select locking behavior for cached provider resolution.

    Use these values for provider-level ``lock_mode`` or container-level
    defaults. Container methods also accept ``"auto"`` at configuration time:
    DIWire maps ``"auto"`` to async locks when a graph requires async resolution
    and to thread locks for sync-only graphs.

    In mixed workloads, prefer forcing ``THREAD`` for high-throughput sync cached
    paths when you do not want auto mode to pick async locks.
    """

    THREAD = "thread"
    """Guard cached values with ``threading.Lock`` in synchronous paths."""

    ASYNC = "async"
    """Guard cached values with ``asyncio.Lock`` for async resolution paths."""

    NONE = "none"
    """Disable locking around cache reads/writes for this provider."""
