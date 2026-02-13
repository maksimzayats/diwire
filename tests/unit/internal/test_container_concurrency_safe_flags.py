from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast

import pytest

from diwire import Container, LockMode


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


def test_container_default_lock_mode_auto() -> None:
    container = Container()
    container.add(ConcreteService)

    assert container._providers_registrations.get_by_type(ConcreteService).lock_mode == "auto"


def test_registration_default_from_container_applies_to_all_non_instance_registrations() -> None:
    def build_factory() -> FactoryService:
        return FactoryService()

    def build_generator() -> Generator[GeneratorService, None, None]:
        yield GeneratorService()

    @contextmanager
    def build_context_manager() -> Generator[ContextManagerService, None, None]:
        yield ContextManagerService()

    container = Container(lock_mode=LockMode.NONE)
    container.add_instance(InstanceService())
    container.add(ConcreteService)
    container.add_factory(build_factory)
    container.add_generator(build_generator)
    container.add_context_manager(build_context_manager)

    assert (
        container._providers_registrations.get_by_type(InstanceService).lock_mode is LockMode.NONE
    )
    assert (
        container._providers_registrations.get_by_type(ConcreteService).lock_mode is LockMode.NONE
    )
    assert container._providers_registrations.get_by_type(FactoryService).lock_mode is LockMode.NONE
    assert (
        container._providers_registrations.get_by_type(GeneratorService).lock_mode is LockMode.NONE
    )
    assert (
        container._providers_registrations.get_by_type(ContextManagerService).lock_mode
        is LockMode.NONE
    )


def test_registration_override_lock_mode_takes_precedence() -> None:
    def build_factory() -> OverrideFactoryService:
        return OverrideFactoryService()

    def build_generator() -> Generator[OverrideGeneratorService, None, None]:
        yield OverrideGeneratorService()

    @contextmanager
    def build_context_manager() -> Generator[OverrideContextManagerService, None, None]:
        yield OverrideContextManagerService()

    def build_decorated_factory() -> OverrideDecoratedFactoryService:
        return OverrideDecoratedFactoryService()

    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(build_factory, lock_mode=LockMode.THREAD)
    container.add(OverrideConcreteService, lock_mode=LockMode.ASYNC)
    container.add_generator(build_generator, lock_mode=LockMode.NONE)
    container.add_context_manager(
        build_context_manager,
        lock_mode=LockMode.ASYNC,
    )

    container.add_factory(
        build_decorated_factory,
        provides=OverrideDecoratedFactoryService,
        lock_mode=LockMode.THREAD,
    )

    assert (
        container._providers_registrations.get_by_type(OverrideConcreteService).lock_mode
        is LockMode.ASYNC
    )
    assert (
        container._providers_registrations.get_by_type(OverrideFactoryService).lock_mode
        is LockMode.THREAD
    )
    assert (
        container._providers_registrations.get_by_type(OverrideGeneratorService).lock_mode
        is LockMode.NONE
    )
    assert (
        container._providers_registrations.get_by_type(OverrideDecoratedFactoryService).lock_mode
        is LockMode.THREAD
    )
    assert (
        container._providers_registrations.get_by_type(OverrideContextManagerService).lock_mode
        is LockMode.ASYNC
    )


def test_register_instance_rejects_lock_mode_argument() -> None:
    container = Container()

    with pytest.raises(TypeError, match="lock_mode"):
        cast("Any", container.add_instance)(
            instance=InstanceService(),
            lock_mode=LockMode.THREAD,
        )
