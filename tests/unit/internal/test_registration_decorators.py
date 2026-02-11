from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import pytest

from diwire import (
    Container,
    add_concrete,
    add_context_manager,
    add_factory,
    add_generator,
)
from diwire.container_context import container_context


@pytest.fixture(autouse=True)
def _reset_container_context_state() -> Generator[None, None, None]:
    previous_container = container_context._container
    previous_operations = list(container_context._operations)
    container_context._container = None
    container_context._operations = []
    try:
        yield
    finally:
        container_context._container = previous_container
        container_context._operations = previous_operations


def test_add_concrete_wrapper_direct_and_decorator_forms() -> None:
    class ConcreteDirectService:
        pass

    class ConcreteAliasService:
        pass

    class ConcreteDecoratedService(ConcreteAliasService):
        pass

    container = Container(autoregister_concrete_types=False)
    container_context.set_current(container)

    returned_direct = add_concrete(ConcreteDirectService)
    assert returned_direct is ConcreteDirectService
    assert isinstance(container.resolve(ConcreteDirectService), ConcreteDirectService)

    @add_concrete(provides=ConcreteAliasService)
    class DecoratedConcrete(ConcreteDecoratedService):
        pass

    assert DecoratedConcrete is not None
    assert isinstance(container.resolve(ConcreteAliasService), ConcreteDecoratedService)


def test_add_factory_wrapper_direct_and_decorator_forms() -> None:
    class FactoryDirectService:
        pass

    class FactoryAliasService:
        pass

    container = Container(autoregister_concrete_types=False)
    container_context.set_current(container)

    def build_direct() -> FactoryDirectService:
        return FactoryDirectService()

    returned_direct = add_factory(build_direct, provides=FactoryDirectService)
    assert returned_direct is build_direct
    assert isinstance(container.resolve(FactoryDirectService), FactoryDirectService)

    @add_factory(provides=FactoryAliasService)
    def build_alias() -> FactoryAliasService:
        return FactoryAliasService()

    assert build_alias is not None
    assert isinstance(container.resolve(FactoryAliasService), FactoryAliasService)


def test_add_generator_wrapper_direct_and_decorator_forms() -> None:
    class GeneratorDirectService:
        pass

    class GeneratorAliasService:
        pass

    container = Container(autoregister_concrete_types=False)
    container_context.set_current(container)

    def build_direct() -> Generator[GeneratorDirectService, None, None]:
        yield GeneratorDirectService()

    returned_direct = add_generator(build_direct, provides=GeneratorDirectService)
    assert returned_direct is build_direct
    with container.enter_scope() as resolver:
        assert isinstance(resolver.resolve(GeneratorDirectService), GeneratorDirectService)

    @add_generator(provides=GeneratorAliasService)
    def build_alias() -> Generator[GeneratorAliasService, None, None]:
        yield GeneratorAliasService()

    assert build_alias is not None
    with container.enter_scope() as resolver:
        assert isinstance(resolver.resolve(GeneratorAliasService), GeneratorAliasService)


def test_add_context_manager_wrapper_direct_and_decorator_forms() -> None:
    class ContextManagerDirectService:
        pass

    class ContextManagerAliasService:
        pass

    container = Container(autoregister_concrete_types=False)
    container_context.set_current(container)

    @contextmanager
    def build_direct() -> Generator[ContextManagerDirectService, None, None]:
        yield ContextManagerDirectService()

    returned_direct = add_context_manager(build_direct, provides=ContextManagerDirectService)
    assert returned_direct is build_direct
    with container.enter_scope() as resolver:
        assert isinstance(
            resolver.resolve(ContextManagerDirectService),
            ContextManagerDirectService,
        )

    @add_context_manager(provides=ContextManagerAliasService)
    @contextmanager
    def build_alias() -> Generator[ContextManagerAliasService, None, None]:
        yield ContextManagerAliasService()

    assert build_alias is not None
    with container.enter_scope() as resolver:
        assert isinstance(resolver.resolve(ContextManagerAliasService), ContextManagerAliasService)
