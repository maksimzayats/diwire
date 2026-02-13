class DIWireError(Exception):
    """Represent a base class for all DIWire-specific failures.

    Catch this type when you want to handle any DIWire error path without
    matching each concrete exception class individually.
    """


class DIWireInvalidRegistrationError(DIWireError):
    """Signal invalid registration or injection configuration.

    Raised by registration APIs such as ``Container.add_concrete``,
    ``Container.add_factory``, ``Container.add_generator``,
    ``Container.add_context_manager``, and by ``ProviderContext.inject`` when
    arguments are invalid.

    Typical fixes include providing valid ``provides``/``scope``/``lifetime``
    values, ensuring providers are callable with valid type annotations, and
    avoiding reserved injection parameter names.
    """


class DIWireInvalidProviderSpecError(DIWireError):
    """Signal an invalid provider specification payload.

    This error is raised while validating provider metadata before resolver
    generation, for example when explicit dependencies do not match the
    provider signature.
    """


class DIWireProviderDependencyInferenceError(DIWireInvalidProviderSpecError):
    """Signal that required provider dependencies cannot be inferred.

    Common triggers are missing or unresolvable type annotations on required
    provider parameters.

    Typical fixes include adding concrete parameter annotations or passing
    explicit ``dependencies=...`` during registration.
    """


class DIWireDependencyNotRegisteredError(DIWireError):
    """Signal that a dependency key has no provider.

    Raised by ``resolve``/``aresolve`` when strict mode is used (autoregistration
    disabled) or when no matching open-generic registration exists.

    Typical fixes include registering the dependency explicitly, enabling
    autoregistration for eligible concrete types, or registering an open-generic
    provider for the requested closed generic key.
    """


class DIWireProviderNotSetError(DIWireError):
    """Signal use of ``provider_context`` with no resolver source available.

    Raised by ``ProviderContext.resolve``, ``ProviderContext.aresolve``,
    ``ProviderContext.enter_scope``, and ``ProviderContext.inject`` call paths
    when neither an active resolver context nor a fallback container can serve
    the call.

    Typical fixes are entering a resolver context (``with container.compile():``)
    or passing an explicit resolver via ``diwire_resolver=...``.
    """


class DIWireScopeMismatchError(DIWireError):
    """Signal scope transition or resolution at an invalid scope depth.

    Raised by ``enter_scope`` for invalid transitions and by ``resolve``/``aresolve``
    when a dependency requires a deeper scope than the current resolver.

    Typical fixes include entering the required scope (for example
    ``with container.enter_scope(Scope.REQUEST): ...``) or adjusting provider
    scopes/lifetimes.
    """


class DIWireAsyncDependencyInSyncContextError(DIWireError):
    """Signal sync resolution of an async dependency chain.

    Raised by ``Container.resolve`` or sync cleanup paths when the selected
    provider graph requires asynchronous resolution/cleanup.

    Typical fix is switching to ``await container.aresolve(...)`` or using
    ``async with`` for scoped cleanup.
    """


class DIWireInvalidGenericTypeArgumentError(DIWireError):
    """Signal invalid closed-generic arguments for an open registration.

    Raised while matching open-generic registrations when a closed key violates
    TypeVar bounds or constraints, or when unresolved TypeVars remain after
    substitution.

    Typical fixes include resolving a compatible closed generic key or tightening
    open-generic provider annotations to reflect valid constraints.
    """
