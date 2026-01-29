"""Custom exceptions for the diwire dependency injection library."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from diwire.service_key import ServiceKey


class DIWireError(Exception):
    """Base exception for all diwire errors."""


class DIWireServiceNotRegisteredError(DIWireError):
    """Service not registered and auto-registration disabled."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(f"Service {service_key} is not registered.")


class DIWireMissingDependenciesError(DIWireError):
    """Service cannot be resolved due to missing dependencies."""

    def __init__(self, service_key: ServiceKey, missing: list[ServiceKey]) -> None:
        self.service_key = service_key
        self.missing = missing
        super().__init__(
            f"Cannot resolve service {service_key} due to missing dependencies: {missing}",
        )


class DIWireAutoRegistrationError(DIWireError):
    """Base for auto-registration failures."""


class DIWireComponentSpecifiedError(DIWireAutoRegistrationError):
    """Cannot auto-register service key with a component."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Cannot auto-register service key {service_key!r} which has a component specified.",
        )


class DIWireIgnoredServiceError(DIWireAutoRegistrationError):
    """Cannot auto-register service in ignore list."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Cannot auto-register service key {service_key!r} which is in the ignore list.",
        )


class DIWireNotAClassError(DIWireAutoRegistrationError):
    """Cannot auto-register non-class value."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(f"Cannot auto-register service key {service_key!r} which is not a class.")


class DIWireUnionTypeError(DIWireAutoRegistrationError):
    """Cannot auto-register a union type."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Cannot auto-register union type {service_key!r}. "
            f"Union types must be explicitly registered with a factory.",
        )


class DIWireCircularDependencyError(DIWireError):
    """Circular dependency detected during resolution."""

    def __init__(self, service_key: ServiceKey, resolution_chain: list[ServiceKey]) -> None:
        self.service_key = service_key
        self.resolution_chain = resolution_chain
        chain_str = " -> ".join(
            str(sk.value.__name__ if hasattr(sk.value, "__name__") else sk.value)
            for sk in resolution_chain
        )
        chain_str += f" -> {service_key.value.__name__ if hasattr(service_key.value, '__name__') else service_key.value}"
        super().__init__(f"Circular dependency detected: {chain_str}")


class DIWireScopeMismatchError(DIWireError):
    """Service is being resolved outside its registered scope."""

    def __init__(
        self,
        service_key: ServiceKey,
        registered_scope: str,
        current_scope: str | None,
    ) -> None:
        self.service_key = service_key
        self.registered_scope = registered_scope
        self.current_scope = current_scope
        current = current_scope or "no active scope"
        super().__init__(
            f"Service {service_key} is registered for scope '{registered_scope}' "
            f"but is being resolved in '{current}'.",
        )


class DIWireScopedWithoutScopeError(DIWireError):
    """SCOPED registered without a scope."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Service {service_key} is registered as SCOPED but no scope was provided. "
            f"SCOPED requires a scope parameter.",
        )


class DIWireGeneratorFactoryWithoutScopeError(DIWireError):
    """Factory returned a generator without an active scope."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Factory for service {service_key} returned a generator, but no active scope exists. "
            "Resolve the service within a scope (enter_scope) to ensure cleanup.",
        )


class DIWireGeneratorFactoryDidNotYieldError(DIWireError):
    """Factory returned a generator that yielded no value."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Factory for service {service_key} returned a generator that did not yield a value.",
        )


class DIWireGeneratorFactoryUnsupportedLifetimeError(DIWireError):
    """Factory returned a generator for an unsupported lifetime."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Factory for service {service_key} returned a generator, but generator factories "
            "require scoped or transient lifetimes within an active scope.",
        )


class DIWireAsyncDependencyInSyncContextError(DIWireError):
    """Attempted to resolve an async dependency using synchronous resolve()."""

    def __init__(self, service_key: ServiceKey, async_dep: ServiceKey) -> None:
        self.service_key = service_key
        self.async_dep = async_dep
        super().__init__(
            f"Cannot resolve {service_key} synchronously because it depends on async dependency "
            f"{async_dep}. Use 'await container.aresolve({service_key})' instead.",
        )


class DIWireAsyncGeneratorFactoryWithoutScopeError(DIWireError):
    """Async generator factory used without an active scope."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Factory for service {service_key} is an async generator, but no active scope exists. "
            "Resolve the service within an async scope (async with container.enter_scope()) "
            "to ensure proper cleanup.",
        )


class DIWireAsyncGeneratorFactoryDidNotYieldError(DIWireError):
    """Async generator factory did not yield a value."""

    def __init__(self, service_key: ServiceKey) -> None:
        self.service_key = service_key
        super().__init__(
            f"Async generator factory for service {service_key} did not yield a value.",
        )


class DIWireContainerNotSetError(DIWireError):
    """No container set in current context."""

    def __init__(self) -> None:
        super().__init__(
            "No container set in current context. "
            "Call container_context.set_current(container) first.",
        )


class DIWireDependencyExtractionError(DIWireError):
    """Failed to extract dependencies from a type."""

    def __init__(self, service_key: ServiceKey, cause: Exception) -> None:
        self.service_key = service_key
        self.cause = cause
        super().__init__(f"Failed to extract dependencies from {service_key}: {cause}")


class DIWireConcreteClassRequiresClassError(DIWireError):
    """The 'concrete_class' parameter requires a class type."""

    def __init__(self, concrete_class: object) -> None:
        self.concrete_class = concrete_class
        super().__init__(
            f"'concrete_class' must be a class type, "
            f"got {type(concrete_class).__name__}: {concrete_class}",
        )


class DIWireAsyncCleanupWithoutEventLoopError(DIWireError):
    """Async cleanup required but no event loop is running."""

    def __init__(self, scope_name: str | None) -> None:
        self.scope_name = scope_name
        scope_desc = f"'{scope_name}'" if scope_name else "anonymous scope"
        super().__init__(
            f"Scope {scope_desc} has async resources that need cleanup, but no event loop is "
            "running. Use 'async with container.enter_scope()' instead of 'with' when resolving "
            "async generators, or ensure an event loop is running when the scope exits.",
        )


class DIWireDecoratorFactoryMissingReturnAnnotationError(DIWireError):
    """Raised when factory decorator cannot determine service type.

    This happens when:
    - No explicit key is given, AND
    - The function has no return type annotation (or returns None)
    """

    def __init__(self, factory: object) -> None:
        self.factory = factory
        factory_name = getattr(factory, "__name__", repr(factory))
        super().__init__(
            f"Factory '{factory_name}' has no return annotation. "
            f"Either add a return type annotation or use @container.register(SomeType).",
        )


class DIWireOpenGenericRegistrationError(DIWireError):
    """Open generic registration is invalid or unsupported."""

    def __init__(self, service_key: ServiceKey, reason: str) -> None:
        self.service_key = service_key
        self.reason = reason
        super().__init__(f"Invalid open generic registration for {service_key}: {reason}")


class DIWireOpenGenericResolutionError(DIWireError):
    """Cannot resolve an open or partially open generic."""

    def __init__(self, service_key: ServiceKey, reason: str) -> None:
        self.service_key = service_key
        self.reason = reason
        super().__init__(f"Cannot resolve generic {service_key}: {reason}")


class DIWireInvalidGenericTypeArgumentError(DIWireError):
    """Type argument does not satisfy TypeVar constraints or bounds."""

    def __init__(self, service_key: ServiceKey, typevar: Any, arg: Any, reason: str) -> None:
        self.service_key = service_key
        self.typevar = typevar
        self.arg = arg
        self.reason = reason
        typevar_name = getattr(typevar, "__name__", repr(typevar))
        super().__init__(
            f"Invalid type argument for {service_key}: {typevar_name}={arg!r}. {reason}",
        )


class DIWireContainerClosedError(DIWireError):
    """Operation attempted on a closed container."""

    def __init__(self) -> None:
        super().__init__("Cannot perform operation on a closed container.")
