from __future__ import annotations

import datetime
import decimal
import inspect
import pathlib
import uuid
from dataclasses import dataclass
from typing import Any, TypeGuard

from diwire._internal.type_checks import is_runtime_class


@dataclass(frozen=True, slots=True)
class ConcreteTypeAutoregistrationPolicy:
    """Internal policy for concrete-type autoregistration eligibility."""

    ignored_base_types: tuple[type[Any], ...] = (
        pathlib.PurePath,
        datetime.datetime,
        datetime.date,
        datetime.time,
        datetime.timedelta,
        uuid.UUID,
        decimal.Decimal,
    )

    def is_eligible_concrete(self, candidate: object) -> TypeGuard[type[Any]]:
        """Return true when a candidate can be auto-registered as a concrete provider.

        Args:
            candidate: Value being checked for eligibility or runtime type constraints.

        """
        if not is_runtime_class(candidate):
            return False
        if candidate.__module__ == "builtins":
            return False
        if inspect.isabstract(candidate):
            return False
        if issubclass(candidate, type):
            return False
        return not issubclass(candidate, self.ignored_base_types)
