from __future__ import annotations

import types
from typing import Any, TypeGuard


def is_runtime_class(candidate: object) -> TypeGuard[type[Any]]:
    """Return true when candidate is a runtime class safe for class-only operations."""
    return isinstance(candidate, type) and not isinstance(candidate, types.GenericAlias)


__all__ = ["is_runtime_class"]
