from __future__ import annotations

import inspect

from diwire.exceptions import DIWireInvalidRegistrationError


class DependecyRegistrationValidator:
    """Validates dependency registrations before creating provider specs."""

    def validate_concrete_type(self, concrete_type: object) -> None:
        """Validate that a concrete provider is instantiable."""
        if not inspect.isclass(concrete_type):
            msg = f"Concrete provider must be a class, got {concrete_type!r}."
            raise DIWireInvalidRegistrationError(msg)

        if inspect.isabstract(concrete_type):
            msg = f"Concrete provider '{concrete_type.__qualname__}' cannot be an abstract class."
            raise DIWireInvalidRegistrationError(msg)
