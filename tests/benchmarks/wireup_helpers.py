from __future__ import annotations

import sys
import warnings
from typing import Any

from wireup import SyncContainer, create_sync_container


def make_wireup_benchmark_container(*injectables: Any) -> SyncContainer:
    with warnings.catch_warnings():
        if sys.version_info >= (3, 13):
            warnings.filterwarnings(
                "ignore",
                category=DeprecationWarning,
            )
        return create_sync_container(
            injectables=list(injectables),
            concurrent_scoped_access=False,
        )
