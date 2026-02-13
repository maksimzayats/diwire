from __future__ import annotations

import inspect
import typing
from collections.abc import AsyncGenerator, Awaitable, Coroutine, Generator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from types import TracebackType
from typing import Annotated, Any, cast

import pytest

from diwire._internal.providers import (
    ContextManagerProvider,
    GeneratorProvider,
    ProviderReturnTypeExtractor,
)
from diwire.exceptions import DIWireInvalidRegistrationError


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


def test_context_manager_class_with_missing_enter_annotation_raises_error() -> None:
    class MissingEnterAnnotationContextManager:
        def __enter__(self) -> Any:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return None

    MissingEnterAnnotationContextManager.__enter__.__annotations__.pop("return")
    extractor = ProviderReturnTypeExtractor()
    bad_context_manager = cast("ContextManagerProvider[Any]", MissingEnterAnnotationContextManager)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        extractor.extract_from_context_manager(bad_context_manager)


def test_context_manager_class_with_invalid_async_enter_annotation_raises_error() -> None:
    class InvalidAsyncContextManager:
        def __aenter__(self) -> Any:
            raise NotImplementedError

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    InvalidAsyncContextManager.__aenter__.__annotations__["return"] = typing.Awaitable
    extractor = ProviderReturnTypeExtractor()
    bad_context_manager = cast("ContextManagerProvider[Any]", InvalidAsyncContextManager)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        extractor.extract_from_context_manager(bad_context_manager)


def test_factory_with_bare_awaitable_return_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    build_service.__annotations__["return"] = typing.Awaitable

    extractor = ProviderReturnTypeExtractor()

    with pytest.raises(DIWireInvalidRegistrationError, match="factory provider"):
        extractor.extract_from_factory(build_service)


def test_factory_with_bare_coroutine_return_annotation_raises_error() -> None:
    def build_service() -> Service:
        return Service()

    build_service.__annotations__["return"] = typing.Coroutine

    extractor = ProviderReturnTypeExtractor()

    with pytest.raises(DIWireInvalidRegistrationError, match="factory provider"):
        extractor.extract_from_factory(build_service)


def test_generator_missing_return_annotation_raises_error() -> None:
    def build_service():  # type: ignore[no-untyped-def]
        yield Service()

    extractor = ProviderReturnTypeExtractor()
    bad_generator = cast("GeneratorProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="generator provider"):
        extractor.extract_from_generator(bad_generator)


def test_context_manager_missing_return_annotation_raises_error() -> None:
    @contextmanager
    def build_service():  # type: ignore[no-untyped-def]
        yield Service()

    extractor = ProviderReturnTypeExtractor()
    bad_context_manager = cast("ContextManagerProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        extractor.extract_from_context_manager(bad_context_manager)


def test_generator_with_bare_generator_annotation_raises_error() -> None:
    def build_service() -> Generator[Service, None, None]:
        yield Service()

    build_service.__annotations__["return"] = typing.Generator
    extractor = ProviderReturnTypeExtractor()
    bad_generator = cast("GeneratorProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="generator provider"):
        extractor.extract_from_generator(bad_generator)


def test_context_manager_with_bare_abstract_context_manager_annotation_raises_error() -> None:
    def build_service() -> AbstractContextManager[Service]:
        raise NotImplementedError

    build_service.__annotations__["return"] = AbstractContextManager
    extractor = ProviderReturnTypeExtractor()
    bad_context_manager = cast("ContextManagerProvider[Any]", build_service)

    with pytest.raises(DIWireInvalidRegistrationError, match="context manager provider"):
        extractor.extract_from_context_manager(bad_context_manager)


def test_resolved_return_annotation_handles_bad_signature_callables() -> None:
    class BadSignatureCallable:
        __annotations__ = {}

        @property
        def __signature__(self) -> inspect.Signature:
            raise ValueError("invalid signature")

        def __call__(self) -> Service:
            return Service()

    extractor = ProviderReturnTypeExtractor()
    resolved_return_annotation, annotation_error = extractor._resolved_return_annotation(
        BadSignatureCallable(),
    )

    assert resolved_return_annotation is not Service
    assert isinstance(annotation_error, ValueError)


def test_resolved_return_annotation_uses_raw_signature_after_type_hint_error() -> None:
    def build_service(dep: Service) -> Service:
        return Service()

    build_service.__annotations__["dep"] = "MissingDependency"
    build_service.__annotations__["return"] = Service
    extractor = ProviderReturnTypeExtractor()
    resolved_return_annotation, annotation_error = extractor._resolved_return_annotation(
        build_service,
    )

    assert resolved_return_annotation is Service
    assert isinstance(annotation_error, NameError)


def test_unwrap_annotated_recursively_unwraps_nested_annotations() -> None:
    extractor = ProviderReturnTypeExtractor()
    nested_annotation = Annotated[Annotated[Service, "inner"], "outer"]

    unwrapped = extractor.unwrap_annotated(nested_annotation)

    assert unwrapped is Service
