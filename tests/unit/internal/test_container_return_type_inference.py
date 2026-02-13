from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from types import TracebackType
from typing import Any, cast

import pytest

from diwire import Container
from diwire._internal.providers import ContextManagerProvider, FactoryProvider, GeneratorProvider
from diwire.exceptions import DIWireInvalidRegistrationError


class Service:
    pass


class ExplicitService:
    pass


class DecoratorService:
    pass


class DecoratorConcreteService:
    pass


class ClassContextManagerService:
    def __enter__(self) -> Any:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


TYPING_EXTENSIONS_SELF: Any = type("Self", (), {"__module__": "typing_extensions"})


class TypingExtensionsSelfCM:
    def __enter__(self) -> TYPING_EXTENSIONS_SELF:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


class AsyncClassContextManagerService:
    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


ClassContextManagerService.__enter__.__annotations__["return"] = ClassContextManagerService
AsyncClassContextManagerService.__aenter__.__annotations__["return"] = (
    AsyncClassContextManagerService
)


def build_class_context_manager() -> ClassContextManagerService:
    return ClassContextManagerService()


def test_register_factory_without_provides_infers_registration_key() -> None:
    def build_service() -> Service:
        return Service()

    container = Container()

    container.add_factory(build_service)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert provider_spec.factory is build_service


def test_register_generator_without_provides_infers_registration_key() -> None:
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    container = Container()

    container.add_generator(build_service)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert provider_spec.generator is build_service


def test_register_context_manager_without_provides_infers_registration_key() -> None:
    @contextmanager
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    container = Container()

    container.add_context_manager(build_service)

    provider_spec = container._providers_registrations.get_by_type(Service)
    assert provider_spec.context_manager is build_service


def test_register_context_manager_class_without_provides_infers_registration_key() -> None:
    container = Container()

    container.add_context_manager(ClassContextManagerService)

    provider_spec = container._providers_registrations.get_by_type(ClassContextManagerService)
    assert provider_spec.context_manager is ClassContextManagerService


def test_register_context_manager_provider_annotated_to_return_cm_class() -> None:
    container = Container()

    container.add_context_manager(build_class_context_manager)

    provider_spec = container._providers_registrations.get_by_type(ClassContextManagerService)
    assert provider_spec.context_manager is build_class_context_manager


def test_register_context_manager_class_with_typing_extensions_self_infers_registration_key() -> (
    None
):
    container = Container()

    container.add_context_manager(TypingExtensionsSelfCM)

    provider_spec = container._providers_registrations.get_by_type(TypingExtensionsSelfCM)
    assert provider_spec.context_manager is TypingExtensionsSelfCM


def test_register_async_context_manager_class_without_provides_infers_registration_key() -> None:
    container = Container()

    container.add_context_manager(AsyncClassContextManagerService)

    provider_spec = container._providers_registrations.get_by_type(AsyncClassContextManagerService)
    assert provider_spec.context_manager is AsyncClassContextManagerService
    assert provider_spec.is_async


def test_register_factory_without_provides_and_invalid_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    build_service.__annotations__["return"] = "MissingService"

    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match="factory provider"):
        container.add_factory(build_service)


def test_register_generator_without_provides_and_invalid_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    container = Container()
    bad_generator = cast("GeneratorProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="generator provider"):
        container.add_generator(bad_generator)


def test_register_context_manager_without_provides_and_invalid_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    container = Container()
    bad_context_manager = cast("ContextManagerProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        container.add_context_manager(bad_context_manager)


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

    container.add_factory(typed_bad_factory, provides=ExplicitService)
    factory_spec = container._providers_registrations.get_by_type(ExplicitService)
    assert factory_spec.factory is typed_bad_factory

    container.add_generator(typed_bad_generator, provides=Service)
    generator_spec = container._providers_registrations.get_by_type(Service)
    assert generator_spec.generator is typed_bad_generator

    container.add_context_manager(
        typed_bad_context_manager,
        provides=Service,
    )
    context_spec = container._providers_registrations.get_by_type(Service)
    assert context_spec.context_manager is typed_bad_context_manager

    typed_valid_cm = cast("ContextManagerProvider[Any]", valid_context_manager)
    container.add_context_manager(typed_valid_cm, provides=ExplicitService)
    async_context_spec = container._providers_registrations.get_by_type(ExplicitService)
    assert async_context_spec.context_manager is typed_valid_cm


def test_add_concrete_without_required_provider_argument_raises_type_error() -> None:
    container = Container()

    with pytest.raises(TypeError):
        cast("Any", container).add_concrete()


def test_add_factory_without_required_provider_argument_raises_type_error() -> None:
    container = Container()

    with pytest.raises(TypeError):
        cast("Any", container).add_factory()


def test_add_generator_without_required_provider_argument_raises_type_error() -> None:
    container = Container()

    with pytest.raises(TypeError):
        cast("Any", container).add_generator()


def test_add_context_manager_without_required_provider_argument_raises_type_error() -> None:
    container = Container()

    with pytest.raises(TypeError):
        cast("Any", container).add_context_manager()


def test_register_concrete_with_provides_only_uses_the_same_concrete_type() -> None:
    container = Container()

    container.add_concrete(DecoratorConcreteService)

    provider_spec = container._providers_registrations.get_by_type(DecoratorConcreteService)
    assert provider_spec.concrete_type is DecoratorConcreteService


def test_add_concrete_returns_none_and_registers_provider() -> None:
    container = Container()

    result = cast("Any", container).add_concrete(
        DecoratorConcreteService,
        provides=DecoratorConcreteService,
    )
    assert result is None
    provider_spec = container._providers_registrations.get_by_type(DecoratorConcreteService)
    assert provider_spec.concrete_type is DecoratorConcreteService


def test_add_generator_returns_none_and_registers_provider() -> None:
    def build_service() -> Generator[DecoratorService, None, None]:
        yield DecoratorService()

    container = Container()

    result = cast("Any", container).add_generator(build_service, provides=DecoratorService)
    assert result is None
    provider_spec = container._providers_registrations.get_by_type(DecoratorService)
    assert provider_spec.generator is build_service


def test_add_context_manager_returns_none_and_registers_provider() -> None:
    @contextmanager
    def build_service() -> Generator[DecoratorService, None, None]:
        yield DecoratorService()

    container = Container()

    result = cast("Any", container).add_context_manager(
        build_service,
        provides=DecoratorService,
    )
    assert result is None
    provider_spec = container._providers_registrations.get_by_type(DecoratorService)
    assert provider_spec.context_manager is build_service
