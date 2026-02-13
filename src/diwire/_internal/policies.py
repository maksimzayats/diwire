from enum import Enum


class MissingPolicy(str, Enum):
    """Policy for handling unresolved registrations."""

    ERROR = "error"
    """Raise an error when a requested type is not registered."""

    REGISTER_ROOT = "register_root"
    """Register only the unresolved root type and do not recurse into dependencies."""

    REGISTER_RECURSIVE = "register_recursive"
    """Register the unresolved type and recursively register its dependencies."""


class DependencyRegistrationPolicy(str, Enum):
    """Policy for handling unresolved dependency types."""

    IGNORE = "ignore"
    """Do not auto-register unresolved dependencies."""

    REGISTER_RECURSIVE = "register_recursive"
    """Recursively register unresolved dependencies."""
