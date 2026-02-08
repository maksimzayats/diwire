class DIWireError(Exception):
    """Base class for all DIWire exceptions."""


class DIWireInvalidProviderSpecError(DIWireError):
    """Raised when an invalid spec is provided."""
