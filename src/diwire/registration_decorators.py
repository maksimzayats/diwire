from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeVar, overload

from diwire.container_context import container_context
from diwire.lock_mode import LockMode
from diwire.providers import Lifetime, ProviderDependency
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
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> C: ...


@overload
def add_concrete(
    concrete_type: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[C], C]: ...


def add_concrete(  # noqa: PLR0913
    concrete_type: C | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> C | Callable[[C], C]:
    if concrete_type == "from_decorator":

        def decorator(decorated_concrete: C) -> C:
            container_context.add_concrete(
                decorated_concrete,
                provides=provides,
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
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> FactoryF: ...


@overload
def add_factory(
    factory: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[FactoryF], FactoryF]: ...


def add_factory(  # noqa: PLR0913
    factory: FactoryF | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> FactoryF | Callable[[FactoryF], FactoryF]:
    if factory == "from_decorator":

        def decorator(decorated_factory: FactoryF) -> FactoryF:
            container_context.add_factory(
                decorated_factory,
                provides=provides,
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
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> GeneratorF: ...


@overload
def add_generator(
    generator: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[GeneratorF], GeneratorF]: ...


def add_generator(  # noqa: PLR0913
    generator: GeneratorF | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> GeneratorF | Callable[[GeneratorF], GeneratorF]:
    if generator == "from_decorator":

        def decorator(decorated_generator: GeneratorF) -> GeneratorF:
            container_context.add_generator(
                decorated_generator,
                provides=provides,
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
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> ContextManagerF: ...


@overload
def add_context_manager(
    context_manager: Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> Callable[[ContextManagerF], ContextManagerF]: ...


def add_context_manager(  # noqa: PLR0913
    context_manager: ContextManagerF | Literal["from_decorator"] = "from_decorator",
    *,
    provides: Any | Literal["infer"] = "infer",
    scope: BaseScope | Literal["from_container"] = "from_container",
    lifetime: Lifetime | Literal["from_container"] = "from_container",
    dependencies: list[ProviderDependency] | Literal["infer"] = "infer",
    lock_mode: LockMode | Literal["from_container"] = "from_container",
    autoregister_dependencies: bool | Literal["from_container"] = "from_container",
) -> ContextManagerF | Callable[[ContextManagerF], ContextManagerF]:
    if context_manager == "from_decorator":

        def decorator(decorated_context_manager: ContextManagerF) -> ContextManagerF:
            container_context.add_context_manager(
                decorated_context_manager,
                provides=provides,
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
        scope=scope,
        lifetime=lifetime,
        dependencies=dependencies,
        lock_mode=lock_mode,
        autoregister_dependencies=autoregister_dependencies,
    )
    return context_manager
