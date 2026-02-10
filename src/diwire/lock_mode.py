from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias

AutoLockMode: TypeAlias = Literal["auto"]
AUTO_LOCK_MODE: AutoLockMode = "auto"


class LockMode(Enum):
    """Locking strategy used by cached provider resolution."""

    THREAD = "thread"
    """Use thread locks for sync cached resolution paths."""

    ASYNC = "async"
    """Use async locks for async-required cached resolution paths."""

    NONE = "none"
    """Disable lock usage for cached resolution paths."""
