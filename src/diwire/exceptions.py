class DIWireError(Exception):
    """Base class for all DIWire exceptions."""


class DIWireInvalidRegistrationError(DIWireError):
    """Raised when an invalid registration is attempted."""


class DIWireInvalidProviderSpecError(DIWireError):
    """Raised when an invalid spec is provided."""


class DIWireProviderDependencyInferenceError(DIWireInvalidProviderSpecError):
    """Raised when provider dependencies cannot be inferred."""
