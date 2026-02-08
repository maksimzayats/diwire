from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from diwire.container import Container


class InstanceService:
    pass


class ConcreteService:
    pass


class FactoryService:
    pass


class GeneratorService:
    pass


class ContextManagerService:
    pass


class OverrideInstanceService:
    pass


class OverrideConcreteService:
    pass


class OverrideFactoryService:
    pass


class OverrideGeneratorService:
    pass


class OverrideContextManagerService:
    pass


class OverrideDecoratedFactoryService:
    pass


def test_container_default_concurrency_safe_applies_to_all_registrations() -> None:
    def build_factory() -> FactoryService:
        return FactoryService()

    def build_generator() -> Generator[GeneratorService, None, None]:
        yield GeneratorService()

    @contextmanager
    def build_context_manager() -> Generator[ContextManagerService, None, None]:
        yield ContextManagerService()

    container = Container(default_concurrency_safe=False)
    container.register_instance(instance=InstanceService())
    container.register_concrete(concrete_type=ConcreteService)
    container.register_factory(factory=build_factory)
    container.register_generator(generator=build_generator)
    container.register_context_manager(context_manager=build_context_manager)

    assert not container._providers_registrations.get_by_type(InstanceService).concurrency_safe
    assert not container._providers_registrations.get_by_type(ConcreteService).concurrency_safe
    assert not container._providers_registrations.get_by_type(FactoryService).concurrency_safe
    assert not container._providers_registrations.get_by_type(GeneratorService).concurrency_safe
    assert not container._providers_registrations.get_by_type(
        ContextManagerService,
    ).concurrency_safe


def test_registration_override_concurrency_safe_takes_precedence() -> None:
    def build_factory() -> OverrideFactoryService:
        return OverrideFactoryService()

    def build_generator() -> Generator[OverrideGeneratorService, None, None]:
        yield OverrideGeneratorService()

    @contextmanager
    def build_context_manager() -> Generator[OverrideContextManagerService, None, None]:
        yield OverrideContextManagerService()

    def build_decorated_factory() -> OverrideDecoratedFactoryService:
        return OverrideDecoratedFactoryService()

    container = Container(default_concurrency_safe=False)
    container.register_instance(instance=OverrideInstanceService(), concurrency_safe=True)
    container.register_factory(factory=build_factory, concurrency_safe=True)
    container.register_concrete(concrete_type=OverrideConcreteService, concurrency_safe=True)
    container.register_generator(generator=build_generator, concurrency_safe=True)
    container.register_context_manager(context_manager=build_context_manager, concurrency_safe=True)

    decorator = container.register_factory(
        OverrideDecoratedFactoryService,
        concurrency_safe=True,
    )
    decorator(build_decorated_factory)

    assert container._providers_registrations.get_by_type(OverrideInstanceService).concurrency_safe
    assert container._providers_registrations.get_by_type(OverrideConcreteService).concurrency_safe
    assert container._providers_registrations.get_by_type(OverrideFactoryService).concurrency_safe
    assert container._providers_registrations.get_by_type(OverrideGeneratorService).concurrency_safe
    assert container._providers_registrations.get_by_type(
        OverrideDecoratedFactoryService,
    ).concurrency_safe
    assert container._providers_registrations.get_by_type(
        OverrideContextManagerService,
    ).concurrency_safe
