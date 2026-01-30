from __future__ import annotations

import asyncio
import threading

from diwire.service_key import ServiceKey


class LockManager:
    """Manages per-key locks for singleton and scoped singleton resolution.

    Provides both async (asyncio.Lock) and sync (threading.Lock) variants
    for singleton and scoped singleton resolution to prevent race conditions.
    """

    __slots__ = (
        "_scoped_singleton_locks",
        "_scoped_singleton_locks_lock",
        "_singleton_locks",
        "_singleton_locks_lock",
        "_sync_scoped_singleton_locks",
        "_sync_scoped_singleton_locks_lock",
        "_sync_singleton_locks",
        "_sync_singleton_locks_lock",
    )

    def __init__(self) -> None:
        # Per-cache-key locks for async scoped singleton resolution to prevent races
        self._scoped_singleton_locks: dict[
            tuple[tuple[tuple[str | None, int], ...], ServiceKey],
            asyncio.Lock,
        ] = {}
        self._scoped_singleton_locks_lock = asyncio.Lock()

        # Per-cache-key locks for sync scoped singleton resolution to prevent races
        self._sync_scoped_singleton_locks: dict[
            tuple[tuple[tuple[str | None, int], ...], ServiceKey],
            threading.Lock,
        ] = {}
        self._sync_scoped_singleton_locks_lock = threading.Lock()

        # Per-service-key locks for async singleton resolution to prevent race conditions
        self._singleton_locks: dict[ServiceKey, asyncio.Lock] = {}
        self._singleton_locks_lock = asyncio.Lock()

        # Per-service-key locks for sync singleton resolution to prevent race conditions
        self._sync_singleton_locks: dict[ServiceKey, threading.Lock] = {}
        self._sync_singleton_locks_lock = threading.Lock()

    async def get_scoped_singleton_lock(
        self,
        cache_key: tuple[tuple[tuple[str | None, int], ...], ServiceKey],
    ) -> asyncio.Lock:
        """Get or create an async lock for scoped singleton resolution of the cache key.

        Uses try/except for the fast path and double-checked locking for safety.
        """
        try:
            return self._scoped_singleton_locks[cache_key]
        except KeyError:
            pass
        async with self._scoped_singleton_locks_lock:
            # Second check after acquiring lock - race timing dependent
            if (
                cache_key not in self._scoped_singleton_locks
            ):  # pragma: no cover - race timing dependent
                self._scoped_singleton_locks[cache_key] = asyncio.Lock()
        return self._scoped_singleton_locks[cache_key]

    def get_sync_scoped_singleton_lock(
        self,
        cache_key: tuple[tuple[tuple[str | None, int], ...], ServiceKey],
    ) -> threading.Lock:
        """Get or create a thread lock for scoped singleton resolution of the cache key.

        Uses try/except for the fast path and double-checked locking for safety.
        """
        try:
            return self._sync_scoped_singleton_locks[cache_key]
        except KeyError:
            pass
        with self._sync_scoped_singleton_locks_lock:
            # Second check after acquiring lock - race timing dependent
            if (
                cache_key not in self._sync_scoped_singleton_locks
            ):  # pragma: no cover - race timing dependent
                self._sync_scoped_singleton_locks[cache_key] = threading.Lock()
        return self._sync_scoped_singleton_locks[cache_key]

    async def get_singleton_lock(self, key: ServiceKey) -> asyncio.Lock:
        """Get or create an async lock for singleton resolution of the given service key.

        Uses try/except for the fast path and double-checked locking for safety.
        """
        try:
            return self._singleton_locks[key]
        except KeyError:
            pass
        async with self._singleton_locks_lock:
            # Second check after acquiring lock - race timing dependent
            if key not in self._singleton_locks:  # pragma: no cover - race timing dependent
                self._singleton_locks[key] = asyncio.Lock()
        return self._singleton_locks[key]

    def get_sync_singleton_lock(self, key: ServiceKey) -> threading.Lock:
        """Get or create a thread lock for singleton resolution of the given service key.

        Uses try/except for the fast path and double-checked locking for safety.
        """
        try:
            return self._sync_singleton_locks[key]
        except KeyError:
            pass
        with self._sync_singleton_locks_lock:
            # Second check after acquiring lock - race timing dependent
            if key not in self._sync_singleton_locks:  # pragma: no cover - race timing dependent
                self._sync_singleton_locks[key] = threading.Lock()
        return self._sync_singleton_locks[key]

    def clear_scope_locks(
        self,
        scope_key: tuple[tuple[str | None, int], ...],
    ) -> None:
        """Remove all locks associated with a scope key."""
        # Snapshot keys to avoid RuntimeError from dict mutation during iteration
        scoped_lock_keys = [k for k in list(self._sync_scoped_singleton_locks) if k[0] == scope_key]
        for k in scoped_lock_keys:
            del self._sync_scoped_singleton_locks[k]
        async_scoped_lock_keys = [
            k for k in list(self._scoped_singleton_locks) if k[0] == scope_key
        ]
        for k in async_scoped_lock_keys:
            del self._scoped_singleton_locks[k]
