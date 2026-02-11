"""Registration methods from basic to advanced.

Learn when to use:

1. ``add_instance`` for pre-built objects.
2. ``add_concrete`` for constructor-based creation.
3. ``add_factory`` for custom build logic.
4. ``add_generator`` for resources with teardown on scope exit.
5. ``add_context_manager`` for context-managed resources.
6. Explicit ``dependencies=[ProviderDependency(...)]`` to bypass inference.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from diwire import Container, Lifetime, Scope
from diwire.providers import ProviderDependency


@dataclass(slots=True)
class Config:
    value: str


class ConcreteDependency:
    pass


@dataclass(slots=True)
class FactoryService:
    dependency: ConcreteDependency


class GeneratorResource:
    pass


class ContextManagerResource:
    pass


@dataclass(slots=True)
class UntypedDependency:
    value: str


@dataclass(slots=True)
class ExplicitDependencyService:
    raw_dependency: UntypedDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    config = Config(value="singleton")
    container.add_instance(config, provides=Config)
    instance_singleton = container.resolve(Config) is container.resolve(Config)
    print(f"instance_singleton={instance_singleton}")  # => instance_singleton=True

    container.add_concrete(ConcreteDependency, provides=ConcreteDependency)

    def build_factory(dependency: ConcreteDependency) -> FactoryService:
        return FactoryService(dependency=dependency)

    container.add_factory(build_factory, provides=FactoryService)
    factory_result = container.resolve(FactoryService)
    print(
        f"factory_injected_dep={isinstance(factory_result.dependency, ConcreteDependency)}",
    )  # => factory_injected_dep=True

    generator_state = {"cleaned": False}

    def build_generator_resource() -> Generator[GeneratorResource, None, None]:
        try:
            yield GeneratorResource()
        finally:
            generator_state["cleaned"] = True

    container.add_generator(
        build_generator_resource,
        provides=GeneratorResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(GeneratorResource)
    print(f"generator_cleaned={generator_state['cleaned']}")  # => generator_cleaned=True

    context_state = {"cleaned": False}

    @contextmanager
    def build_context_resource() -> Generator[ContextManagerResource, None, None]:
        try:
            yield ContextManagerResource()
        finally:
            context_state["cleaned"] = True

    container.add_context_manager(
        build_context_resource,
        provides=ContextManagerResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(ContextManagerResource)
    print(f"context_manager_cleaned={context_state['cleaned']}")  # => context_manager_cleaned=True

    raw_dependency = UntypedDependency(value="raw")
    container.add_instance(raw_dependency, provides=UntypedDependency)

    def build_explicit_service(raw_dependency) -> ExplicitDependencyService:  # type: ignore[no-untyped-def]
        return ExplicitDependencyService(raw_dependency=raw_dependency)

    signature = inspect.signature(build_explicit_service)
    explicit_dependencies = [
        ProviderDependency(
            provides=UntypedDependency,
            parameter=signature.parameters["raw_dependency"],
        ),
    ]
    container.add_factory(
        build_explicit_service,
        provides=ExplicitDependencyService,
        dependencies=explicit_dependencies,
    )
    explicit_service = container.resolve(ExplicitDependencyService)
    print(
        f"explicit_deps_ok={explicit_service.raw_dependency is raw_dependency}",
    )  # => explicit_deps_ok=True


if __name__ == "__main__":
    main()
