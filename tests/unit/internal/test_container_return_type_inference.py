from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, cast

import pytest

from diwire.container import (
    ConcreteTypeRegistrationDecorator,
    Container,
    ContextManagerRegistrationDecorator,
    GeneratorRegistrationDecorator,
)
from diwire.exceptions import DIWireInvalidRegistrationError
from diwire.providers import ContextManagerProvider, FactoryProvider, GeneratorProvider


class Service:
    pass


class ExplicitService:
    pass


class DecoratorService:
    pass


class DecoratorConcreteService:
    pass


def test_register_factory_without_provides_infers_registration_key() -> None:
    def build_service() -> Service:
        return Service()

    container = Container()

    container.register_factory(factory=build_service)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert provider_spec.factory is build_service


def test_register_generator_without_provides_infers_registration_key() -> None:
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    container = Container()

    container.register_generator(generator=build_service)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert provider_spec.generator is build_service


def test_register_context_manager_without_provides_infers_registration_key() -> None:
    @contextmanager
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    container = Container()

    container.register_context_manager(context_manager=build_service)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert provider_spec.context_manager is build_service


def test_register_factory_without_provides_and_invalid_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    build_service.__annotations__["return"] = "MissingService"

    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match="factory provider"):
        container.register_factory(factory=build_service)


def test_register_generator_without_provides_and_invalid_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    container = Container()
    bad_generator = cast("GeneratorProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="generator provider"):
        container.register_generator(generator=bad_generator)


def test_register_context_manager_without_provides_and_invalid_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    container = Container()
    bad_context_manager = cast("ContextManagerProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        container.register_context_manager(context_manager=bad_context_manager)


def test_explicit_provides_bypasses_return_type_inference_for_all_provider_kinds() -> None:
    def bad_factory() -> Service:
        return Service()

    def bad_generator() -> Service:
        return Service()

    def bad_context_manager() -> Service:
        return Service()

    @asynccontextmanager
    async def valid_context_manager() -> AsyncGenerator[Service, None]:
        yield Service()

    bad_factory.__annotations__["return"] = "MissingFactoryType"

    container = Container()
    typed_bad_factory = cast("FactoryProvider[ExplicitService]", bad_factory)
    typed_bad_generator = cast("GeneratorProvider[Any]", bad_generator)
    typed_bad_context_manager = cast("ContextManagerProvider[Any]", bad_context_manager)

    container.register_factory(provides=ExplicitService, factory=typed_bad_factory)
    factory_spec = container._providers_registrations.get_by_type(ExplicitService)
    assert factory_spec.factory is typed_bad_factory

    container.register_generator(provides=Service, generator=typed_bad_generator)
    generator_spec = container._providers_registrations.get_by_type(Service)
    assert generator_spec.generator is typed_bad_generator

    container.register_context_manager(
        provides=Service,
        context_manager=typed_bad_context_manager,
    )
    context_spec = container._providers_registrations.get_by_type(Service)
    assert context_spec.context_manager is typed_bad_context_manager

    typed_valid_cm = cast("ContextManagerProvider[Any]", valid_context_manager)
    container.register_context_manager(provides=ExplicitService, context_manager=typed_valid_cm)
    async_context_spec = container._providers_registrations.get_by_type(ExplicitService)
    assert async_context_spec.context_manager is typed_valid_cm


def test_register_concrete_without_arguments_returns_decorator() -> None:
    container = Container()

    assert isinstance(container.register_concrete(), ConcreteTypeRegistrationDecorator)


def test_register_generator_with_none_returns_decorator() -> None:
    container = Container()

    assert isinstance(container.register_generator(generator=None), GeneratorRegistrationDecorator)


def test_register_context_manager_with_none_returns_decorator() -> None:
    container = Container()

    assert isinstance(
        container.register_context_manager(context_manager=None),
        ContextManagerRegistrationDecorator,
    )


def test_register_concrete_with_provides_only_uses_the_same_concrete_type() -> None:
    container = Container()

    container.register_concrete(provides=DecoratorConcreteService)

    provider_spec = container._providers_registrations.get_by_type(DecoratorConcreteService)
    assert provider_spec.concrete_type is DecoratorConcreteService


def test_concrete_decorator_registers_provider() -> None:
    container = Container()

    decorator = container.register_concrete(provides=DecoratorConcreteService)
    returned_type = decorator(DecoratorConcreteService)

    assert returned_type is DecoratorConcreteService
    provider_spec = container._providers_registrations.get_by_type(DecoratorConcreteService)
    assert provider_spec.concrete_type is DecoratorConcreteService


def test_generator_decorator_registers_provider() -> None:
    def build_service() -> Generator[DecoratorService, None, None]:
        yield DecoratorService()

    container = Container()

    decorator = container.register_generator(provides=DecoratorService, generator=None)
    returned_generator = decorator(build_service)

    assert returned_generator is build_service
    provider_spec = container._providers_registrations.get_by_type(DecoratorService)
    assert provider_spec.generator is build_service


def test_context_manager_decorator_registers_provider() -> None:
    @contextmanager
    def build_service() -> Generator[DecoratorService, None, None]:
        yield DecoratorService()

    container = Container()

    decorator = container.register_context_manager(provides=DecoratorService, context_manager=None)
    returned_context_manager = decorator(build_service)

    assert returned_context_manager is build_service
    provider_spec = container._providers_registrations.get_by_type(DecoratorService)
    assert provider_spec.context_manager is build_service
