from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Coroutine, Generator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from typing import Annotated, Any, cast

import pytest

from diwire.exceptions import DIWireInvalidRegistrationError
from diwire.providers import (
    ContextManagerProvider,
    GeneratorProvider,
    ProviderReturnTypeExtractor,
)


class Service:
    pass


def test_factory_extracts_plain_return_type() -> None:
    def build_service() -> Service:
        return Service()

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_factory(build_service)

    assert provides is Service


def test_factory_extracts_async_function_return_type() -> None:
    async def build_service() -> Service:
        return Service()

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_factory(build_service)

    assert provides is Service


def test_factory_unwraps_awaitable_return_type() -> None:
    def build_service() -> Awaitable[Service]:
        raise NotImplementedError

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_factory(build_service)

    assert provides is Service


def test_factory_unwraps_coroutine_return_type() -> None:
    def build_service() -> Coroutine[None, None, Service]:
        raise NotImplementedError

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_factory(build_service)

    assert provides is Service


def test_factory_preserves_annotated_return_type() -> None:
    def build_service() -> Annotated[Service, "primary"]:
        return Service()

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_factory(build_service)

    assert provides == Annotated[Service, "primary"]


def test_factory_missing_or_unresolvable_return_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    build_service.__annotations__["return"] = "MissingService"

    extractor = ProviderReturnTypeExtractor()

    with pytest.raises(DIWireInvalidRegistrationError, match="Original annotation error"):
        extractor.extract_from_factory(build_service)


def test_generator_extracts_yielded_type() -> None:
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_generator(build_service)

    assert provides is Service


def test_generator_extracts_async_yielded_type() -> None:
    async def build_service() -> AsyncGenerator[Service, None]:
        yield Service()

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_generator(build_service)

    assert provides is Service


def test_generator_with_non_generator_return_type_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    extractor = ProviderReturnTypeExtractor()
    bad_generator = cast("GeneratorProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="generator provider"):
        extractor.extract_from_generator(bad_generator)


def test_context_manager_extracts_managed_type_from_abstract_context_manager() -> None:
    def build_service() -> AbstractContextManager[Service]:
        raise NotImplementedError

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_context_manager(build_service)

    assert provides is Service


def test_context_manager_extracts_managed_type_from_abstract_async_context_manager() -> None:
    def build_service() -> AbstractAsyncContextManager[Service]:
        raise NotImplementedError

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_context_manager(build_service)

    assert provides is Service


def test_context_manager_supports_generator_style_annotations() -> None:
    @contextmanager
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    @asynccontextmanager
    async def build_async_service() -> AsyncGenerator[Service, None]:
        yield Service()

    extractor = ProviderReturnTypeExtractor()

    provides = extractor.extract_from_context_manager(build_service)
    async_provides = extractor.extract_from_context_manager(build_async_service)

    assert provides is Service
    assert async_provides is Service


def test_context_manager_with_invalid_return_type_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    extractor = ProviderReturnTypeExtractor()
    bad_context_manager = cast("ContextManagerProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        extractor.extract_from_context_manager(bad_context_manager)
