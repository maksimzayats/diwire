from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, cast

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireInvalidRegistrationError


class Service:
    pass


class AbstractService(ABC):
    @abstractmethod
    def run(self) -> Service:
        """Return a service instance."""


def test_register_concrete_rejects_non_class_concrete_type() -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match="must be a class"):
        container.add_concrete(cast("Any", 42))


def test_register_concrete_rejects_abstract_concrete_type() -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match="abstract class"):
        container.add_concrete(AbstractService)
