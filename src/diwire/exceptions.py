class DIWireError(Exception):
    """Base class for all DIWire exceptions."""


class DIWireInvalidRegistrationError(DIWireError):
    """Raised when an invalid registration is attempted."""


class DIWireInvalidProviderSpecError(DIWireError):
    """Raised when an invalid spec is provided."""


class DIWireProviderDependencyInferenceError(DIWireInvalidProviderSpecError):
    """Raised when provider dependencies cannot be inferred."""


class DIWireDependencyNotRegisteredError(DIWireError):
    """Raised when attempting to resolve a dependency that was not registered."""


class DIWireScopeMismatchError(DIWireError):
    """Raised when dependency resolution requires a scope that is not currently opened."""


class DIWireAsyncDependencyInSyncContextError(DIWireError):
    """Raised when synchronous resolution is attempted for an async dependency chain."""
