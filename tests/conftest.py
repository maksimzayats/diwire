from __future__ import annotations

import pytest

from diwire import Container


@pytest.fixture()
def diwire_container() -> Container:
    """Repository-level override for the pytest plugin container fixture."""
    return Container()
