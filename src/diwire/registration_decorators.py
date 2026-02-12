from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypeVar, overload

from diwire.container_context import container_context
from diwire.lock_mode import LockMode
from diwire.providers import Lifetime
from diwire.scope import BaseScope

C = TypeVar("C", bound=type[Any])
FactoryF = TypeVar("FactoryF", bound=Callable[..., Any])
GeneratorF = TypeVar("GeneratorF", bound=Callable[..., Any])
ContextManagerF = TypeVar("ContextManagerF", bound=Callable[..., Any])


@overload
def add_concrete(
    concrete_type: C,
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> C: ...


@overload
def add_concrete(
    concrete_type: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[C], C]: ...


def add_concrete(  # noqa: PLR0913
    concrete_type: C | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> C | Callable[[C], C]:
    """Register a concrete provider through the global ``container_context``.

    This helper proxies to ``container_context.add_concrete``. It is safe in
    applications that bind ``container_context`` during startup; when unbound it
    records the registration for replay once a container is bound.

    Args:
        concrete_type: Concrete class to register, or ``"from_decorator"`` to
            use decorator form.
        provides: Dependency key exposed by the registration.
        component: Optional component marker value forwarded to the container.
        scope: Registration scope or ``"from_container"``.
        lifetime: Provider lifetime or ``"from_container"``.
        dependencies: Explicit dependency mapping or ``"infer"``.
        lock_mode: Locking mode or ``"from_container"``.
        autoregister_dependencies: Override dependency autoregistration behavior.

    Returns:
        The decorated class in direct form, or a decorator callable in decorator
        form.

    Raises:
        DIWireInvalidRegistrationError: If registration arguments are invalid.

    Examples:
        .. code-block:: python

            @add_concrete()
            class SqlUserRepository(UserRepository): ...

    """
    if concrete_type == "from_decorator":

        def decorator(decorated_concrete: C) -> C:
            container_context.add_concrete(
                decorated_concrete,
                provides=provides,
                component=component,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_concrete

        return decorator

    container_context.add_concrete(
        concrete_type,
        provides=provides,
        component=component,
        scope=scope,
        lifetime=lifetime,
        dependencies=dependencies,
        lock_mode=lock_mode,
        autoregister_dependencies=autoregister_dependencies,
    )
    return concrete_type


@overload
def add_factory(
    factory: FactoryF,
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> FactoryF: ...


@overload
def add_factory(
    factory: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[FactoryF], FactoryF]: ...


def add_factory(  # noqa: PLR0913
    factory: FactoryF | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> FactoryF | Callable[[FactoryF], FactoryF]:
    """Register a factory provider through the global ``container_context``.

    This helper proxies to ``container_context.add_factory``. It is safe when
    the application binds ``container_context`` during startup; before binding,
    registrations are queued and replayed once bound.

    Args:
        factory: Factory callable to register, or ``"from_decorator"``.
        provides: Dependency key exposed by the registration.
        component: Optional component marker value forwarded to the container.
        scope: Registration scope or ``"from_container"``.
        lifetime: Provider lifetime or ``"from_container"``.
        dependencies: Explicit dependency mapping or ``"infer"``.
        lock_mode: Locking mode or ``"from_container"``.
        autoregister_dependencies: Override dependency autoregistration behavior.

    Returns:
        The factory in direct form, or a decorator callable in decorator form.

    Raises:
        DIWireInvalidRegistrationError: If registration arguments are invalid.

    Examples:
        .. code-block:: python

            @add_factory()
            def make_service(repo: UserRepository) -> Service:
                return Service(repo)

    """
    if factory == "from_decorator":

        def decorator(decorated_factory: FactoryF) -> FactoryF:
            container_context.add_factory(
                decorated_factory,
                provides=provides,
                component=component,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_factory

        return decorator

    container_context.add_factory(
        factory,
        provides=provides,
        component=component,
        scope=scope,
        lifetime=lifetime,
        dependencies=dependencies,
        lock_mode=lock_mode,
        autoregister_dependencies=autoregister_dependencies,
    )
    return factory


@overload
def add_generator(
    generator: GeneratorF,
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> GeneratorF: ...


@overload
def add_generator(
    generator: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[GeneratorF], GeneratorF]: ...


def add_generator(  # noqa: PLR0913
    generator: GeneratorF | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> GeneratorF | Callable[[GeneratorF], GeneratorF]:
    """Register a generator provider through the global ``container_context``.

    This helper proxies to ``container_context.add_generator``. It is intended
    for applications that bind ``container_context`` once at startup; if unbound,
    registrations are deferred and replayed later.

    Args:
        generator: Generator/async-generator provider, or ``"from_decorator"``.
        provides: Dependency key exposed by the registration.
        component: Optional component marker value forwarded to the container.
        scope: Registration scope or ``"from_container"``.
        lifetime: Provider lifetime or ``"from_container"``.
        dependencies: Explicit dependency mapping or ``"infer"``.
        lock_mode: Locking mode or ``"from_container"``.
        autoregister_dependencies: Override dependency autoregistration behavior.

    Returns:
        The generator in direct form, or a decorator callable in decorator form.

    Raises:
        DIWireInvalidRegistrationError: If registration arguments are invalid.

    Examples:
        .. code-block:: python

            @add_generator(scope=Scope.REQUEST)
            def make_session(engine: Engine) -> Generator[Session, None, None]:
                with Session(engine) as session:
                    yield session

    """
    if generator == "from_decorator":

        def decorator(decorated_generator: GeneratorF) -> GeneratorF:
            container_context.add_generator(
                decorated_generator,
                provides=provides,
                component=component,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_generator

        return decorator

    container_context.add_generator(
        generator,
        provides=provides,
        component=component,
        scope=scope,
        lifetime=lifetime,
        dependencies=dependencies,
        lock_mode=lock_mode,
        autoregister_dependencies=autoregister_dependencies,
    )
    return generator


@overload
def add_context_manager(
    context_manager: ContextManagerF,
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> ContextManagerF: ...


@overload
def add_context_manager(
    context_manager: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[ContextManagerF], ContextManagerF]: ...


def add_context_manager(  # noqa: PLR0913
    context_manager: ContextManagerF | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    component: object | None = None,
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: Mapping[Any, inspect.Parameter] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> ContextManagerF | Callable[[ContextManagerF], ContextManagerF]:
    """Register a context manager provider through ``container_context``.

    This helper proxies to ``container_context.add_context_manager``. It is
    typically used in applications that bind ``container_context`` during
    startup; when unbound, registrations are recorded for later replay.

    Args:
        context_manager: Context-manager provider callable, or
            ``"from_decorator"``.
        provides: Dependency key exposed by the registration.
        component: Optional component marker value forwarded to the container.
        scope: Registration scope or ``"from_container"``.
        lifetime: Provider lifetime or ``"from_container"``.
        dependencies: Explicit dependency mapping or ``"infer"``.
        lock_mode: Locking mode or ``"from_container"``.
        autoregister_dependencies: Override dependency autoregistration behavior.

    Returns:
        The provider in direct form, or a decorator callable in decorator form.

    Raises:
        DIWireInvalidRegistrationError: If registration arguments are invalid.

    Examples:
        .. code-block:: python

            @add_context_manager(scope=Scope.REQUEST)
            def session(engine: Engine) -> ContextManager[Session]:
                return Session(engine)

    """
    if context_manager == "from_decorator":

        def decorator(decorated_context_manager: ContextManagerF) -> ContextManagerF:
            container_context.add_context_manager(
                decorated_context_manager,
                provides=provides,
                component=component,
                scope=scope,
                lifetime=lifetime,
                dependencies=dependencies,
                lock_mode=lock_mode,
                autoregister_dependencies=autoregister_dependencies,
            )
            return decorated_context_manager

        return decorator

    container_context.add_context_manager(
        context_manager,
        provides=provides,
        component=component,
        scope=scope,
        lifetime=lifetime,
        dependencies=dependencies,
        lock_mode=lock_mode,
        autoregister_dependencies=autoregister_dependencies,
    )
    return context_manager
