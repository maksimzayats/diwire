from __future__ import annotations

import contextlib
import types
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from diwire.exceptions import DIWireScopeMismatchError
from diwire.service_key import ServiceKey

if TYPE_CHECKING:
    from typing_extensions import Self


@dataclass(frozen=True, slots=True)
class _ScopeId:
    """Tuple-based scope identifier for fast scope matching.

    Replaces string-based scope paths to eliminate split/join operations.
    Each segment is a (scope_name, instance_id) pair.
    """

    segments: tuple[tuple[str | None, int], ...]
    _scope_key_by_name: dict[str, tuple[tuple[str | None, int], ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _named_scopes_desc: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        segments = self.segments
        if len(segments) == 1:
            name, _ = segments[0]
            if name is None:
                object.__setattr__(self, "_scope_key_by_name", {})
                object.__setattr__(self, "_named_scopes_desc", ())
                return
            object.__setattr__(self, "_scope_key_by_name", {name: segments})
            object.__setattr__(self, "_named_scopes_desc", (name,))
            return

        scope_key_by_name: dict[str, tuple[tuple[str | None, int], ...]] = {}
        named_scopes_desc: list[str] = []
        for index, (name, _) in enumerate(segments):
            if name is None:
                continue
            if name not in scope_key_by_name:
                scope_key_by_name[name] = segments[: index + 1]
        for name, _ in reversed(segments):
            if name is not None:
                named_scopes_desc.append(name)
        object.__setattr__(self, "_scope_key_by_name", scope_key_by_name)
        object.__setattr__(self, "_named_scopes_desc", tuple(named_scopes_desc))

    @property
    def path(self) -> str:
        """Generate string path only when needed (error messages)."""
        parts = []
        for name, id_ in self.segments:
            parts.append(f"{name}/{id_}" if name else str(id_))
        return "/".join(parts)

    def contains_scope(self, scope_name: str) -> bool:
        """Check if this scope contains the given scope name."""
        return scope_name in self._scope_key_by_name

    def get_cache_key_for_scope(self, scope_name: str) -> tuple[tuple[str | None, int], ...] | None:
        """Get the tuple key up to and including the specified scope segment.

        Returns None if the scope is not found.
        """
        return self._scope_key_by_name.get(scope_name)

    @property
    def named_scopes_desc(self) -> tuple[str, ...]:
        """Return named scopes from most specific to least specific."""
        return self._named_scopes_desc


# Context variable for current scope
_current_scope: ContextVar[_ScopeId | None] = ContextVar("current_scope", default=None)


@dataclass
class ScopedContainer:
    """A context manager for scoped dependency resolution.

    Supports both sync and async context managers:
    - `with container.enter_scope()` for sync usage
    - `async with container.enter_scope()` for async usage with proper async cleanup

    Also supports imperative usage:
    - `scope = container.enter_scope()` to activate immediately
    - `scope.close()` or `scope.aclose()` to close explicitly
    - `container.close()` or `container.aclose()` to close all active scopes
    """

    _container: Any
    _scope_id: _ScopeId
    _token: Any = field(default=None, init=False)
    _exited: bool = field(default=False, init=False)
    _activated: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Activate scope immediately on creation for imperative usage."""
        self._token = _current_scope.set(self._scope_id)
        try:
            self._container._register_active_scope(self)  # noqa: SLF001
            self._activated = True
        except:
            with contextlib.suppress(ValueError, RuntimeError):
                _current_scope.reset(self._token)
            raise

    def resolve(self, key: Any) -> Any:
        """Resolve a service within this scope."""
        if self._exited:
            current = _current_scope.get()
            raise DIWireScopeMismatchError(
                ServiceKey.from_value(key),
                self._scope_id.path,
                current.path if current else None,
            )
        handled, result = self._container._resolve_scoped_compiled(  # noqa: SLF001
            key,
            self._scope_id,
        )
        if handled:
            return result
        return self._container.resolve(key)

    async def aresolve(self, key: Any) -> Any:
        """Asynchronously resolve a service within this scope."""
        if self._exited:
            current = _current_scope.get()
            raise DIWireScopeMismatchError(
                ServiceKey.from_value(key),
                self._scope_id.path,
                current.path if current else None,
            )
        return await self._container.aresolve(key)

    def enter_scope(self, scope_name: str | None = None) -> ScopedContainer:
        """Start a nested scope."""
        return self._container.enter_scope(scope_name)

    def _close_sync(self) -> None:
        """Close the scope synchronously."""
        if self._exited:
            return
        with contextlib.suppress(ValueError, RuntimeError):
            _current_scope.reset(self._token)
        self._container._clear_scope(self._scope_id)  # noqa: SLF001
        self._container._unregister_active_scope(self)  # noqa: SLF001
        self._exited = True

    async def _close_async(self) -> None:
        """Close the scope asynchronously."""
        if self._exited:
            return
        with contextlib.suppress(ValueError, RuntimeError):
            _current_scope.reset(self._token)
        await self._container._aclear_scope(self._scope_id)  # noqa: SLF001
        self._container._unregister_active_scope(self)  # noqa: SLF001
        self._exited = True

    def close(self) -> None:
        """Explicitly close this scope (sync)."""
        self._close_sync()

    async def aclose(self) -> None:
        """Explicitly close this scope (async)."""
        await self._close_async()

    def __enter__(self) -> Self:
        # Scope is already activated in __post_init__, just return self
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self._close_sync()

    async def __aenter__(self) -> Self:
        # Scope is already activated in __post_init__, just return self
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self._close_async()
