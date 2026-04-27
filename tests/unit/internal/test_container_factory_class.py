from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any, cast

import pytest

from diwire import Container, Injected, Lifetime, Scope
from diwire.exceptions import DIWireInvalidRegistrationError


@dataclass(frozen=True)
class _Settings:
    prefix: str


@dataclass(frozen=True)
class _Client:
    name: str


@dataclass(kw_only=True)
class _Events:
    values: list[str]


@dataclass(kw_only=True)
class _ClientFactory:
    settings: Injected[_Settings]

    def __call__(self) -> _Client:
        return _Client(name=f"{self.settings.prefix}-client")


@dataclass(kw_only=True)
class _AsyncClientFactory:
    settings: Injected[_Settings]

    async def __call__(self) -> _Client:
        return _Client(name=f"{self.settings.prefix}-async-client")


@dataclass(kw_only=True)
class _ExplicitClientFactory:
    settings: _Settings

    def __call__(self) -> Any:
        return _Client(name=f"{self.settings.prefix}-explicit-client")


@dataclass(kw_only=True)
class _GeneratorClientFactory:
    events: Injected[_Events]

    def __call__(self) -> Generator[_Client, None, None]:
        self.events.values.append("generator-open")
        try:
            yield _Client(name="generator-client")
        finally:
            self.events.values.append("generator-close")


@dataclass(kw_only=True)
class _GeneratorObjectClientFactory:
    events: Injected[_Events]

    def __call__(self) -> Generator[_Client, None, None]:
        def _build_client() -> Generator[_Client, None, None]:
            self.events.values.append("generator-object-open")
            try:
                yield _Client(name="generator-object-client")
            finally:
                self.events.values.append("generator-object-close")

        return _build_client()


@dataclass(kw_only=True)
class _UnsafeGeneratorClientFactory:
    events: Injected[_Events]

    def __call__(self) -> Generator[_Client, None, None]:
        self.events.values.append("unsafe-generator-open")
        yield _Client(name="unsafe-generator-client")
        self.events.values.append("unsafe-generator-close")


@dataclass(kw_only=True)
class _AsyncGeneratorClientFactory:
    events: Injected[_Events]

    async def __call__(self) -> AsyncGenerator[_Client, None]:
        self.events.values.append("async-generator-open")
        try:
            yield _Client(name="async-generator-client")
        finally:
            self.events.values.append("async-generator-close")


@dataclass(kw_only=True)
class _ContextManagerDecoratorClientFactory:
    events: Injected[_Events]

    @contextmanager
    def __call__(self) -> Generator[_Client, None, None]:
        self.events.values.append("context-manager-decorator-open")
        try:
            yield _Client(name="context-manager-decorator-client")
        finally:
            self.events.values.append("context-manager-decorator-close")


@dataclass(kw_only=True)
class _ClientContext:
    events: _Events

    def __enter__(self) -> _Client:
        self.events.values.append("context-manager-object-open")
        return _Client(name="context-manager-object-client")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.events.values.append("context-manager-object-close")
        return None


@dataclass(kw_only=True)
class _ContextManagerObjectClientFactory:
    events: Injected[_Events]

    def __call__(self) -> _ClientContext:
        return _ClientContext(events=self.events)


class _NotFactory:
    pass


def test_add_factory_class_infers_provides_and_constructor_dependencies() -> None:
    container = Container()
    container.add_instance(_Settings(prefix="main"))

    container.add_factory_class(_ClientFactory)

    resolved = container.resolve(_Client)

    assert resolved == _Client(name="main-client")
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.factory is not None
    assert [dependency.parameter.name for dependency in provider_spec.dependencies] == ["settings"]


async def test_add_factory_class_supports_async_call_method() -> None:
    container = Container()
    container.add_instance(_Settings(prefix="main"))

    container.add_factory_class(_AsyncClientFactory)

    resolved = await container.aresolve(_Client)

    assert resolved == _Client(name="main-async-client")
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.is_async


def test_add_factory_class_supports_explicit_provides_for_untyped_call_method() -> None:
    container = Container(default_lifetime=Lifetime.TRANSIENT)
    container.add_instance(_Settings(prefix="main"))

    container.add_factory_class(_ExplicitClientFactory, provides=_Client)

    first = container.resolve(_Client)
    second = container.resolve(_Client)

    assert first == _Client(name="main-explicit-client")
    assert second == _Client(name="main-explicit-client")
    assert first is not second


def test_add_generator_class_supports_generator_call_method_cleanup() -> None:
    events = _Events(values=[])
    container = Container()
    container.add_instance(events)

    container.add_generator_class(
        _GeneratorClientFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_Client)
        assert resolved == _Client(name="generator-client")
        assert events.values == ["generator-open"]

    assert events.values == ["generator-open", "generator-close"]
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.generator is not None
    assert provider_spec.needs_cleanup


def test_add_generator_class_supports_generator_object_call_method_cleanup() -> None:
    events = _Events(values=[])
    container = Container()
    container.add_instance(events)

    container.add_generator_class(
        _GeneratorObjectClientFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_Client)
        assert resolved == _Client(name="generator-object-client")
        assert events.values == ["generator-object-open"]

    assert events.values == ["generator-object-open", "generator-object-close"]


def test_add_generator_class_can_skip_generator_finally_validation() -> None:
    events = _Events(values=[])
    container = Container()
    container.add_instance(events)

    container.add_generator_class(
        _UnsafeGeneratorClientFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
        require_generator_finally=False,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_Client)
        assert resolved == _Client(name="unsafe-generator-client")


async def test_add_generator_class_supports_async_generator_call_method_cleanup() -> None:
    events = _Events(values=[])
    container = Container()
    container.add_instance(events)

    container.add_generator_class(
        _AsyncGeneratorClientFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_Client)
        assert resolved == _Client(name="async-generator-client")
        assert events.values == ["async-generator-open"]

    assert events.values == ["async-generator-open", "async-generator-close"]
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.generator is not None
    assert provider_spec.is_async
    assert provider_spec.needs_cleanup


def test_add_context_manager_class_supports_context_manager_decorator_cleanup() -> None:
    events = _Events(values=[])
    container = Container()
    container.add_instance(events)

    container.add_context_manager_class(
        _ContextManagerDecoratorClientFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_Client)
        assert resolved == _Client(name="context-manager-decorator-client")
        assert events.values == ["context-manager-decorator-open"]

    assert events.values == ["context-manager-decorator-open", "context-manager-decorator-close"]
    provider_spec = container._providers_registrations.get_by_type(_Client)
    assert provider_spec.context_manager is not None
    assert provider_spec.needs_cleanup


def test_add_context_manager_class_supports_context_manager_object_cleanup() -> None:
    events = _Events(values=[])
    container = Container()
    container.add_instance(events)

    container.add_context_manager_class(
        _ContextManagerObjectClientFactory,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(_Client)
        assert resolved == _Client(name="context-manager-object-client")
        assert events.values == ["context-manager-object-open"]

    assert events.values == ["context-manager-object-open", "context-manager-object-close"]


def test_add_generator_class_rejects_generator_call_method_without_finally() -> None:
    container = Container()
    container.add_instance(_Events(values=[]))

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match=r"add_generator_class\(\) provider .* must place every yield",
    ):
        container.add_generator_class(_UnsafeGeneratorClientFactory)


@pytest.mark.parametrize(
    ("factory_class", "match"),
    [
        (
            cast("Any", object()),
            "add_factory_class\\(\\) parameter 'factory_class' must be a class",
        ),
        (
            _NotFactory,
            "add_factory_class\\(\\) parameter 'factory_class' must define an instance __call__",
        ),
    ],
)
def test_add_factory_class_rejects_invalid_factory_class(
    factory_class: type[Any],
    match: str,
) -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        container.add_factory_class(factory_class)


@pytest.mark.parametrize(
    ("invoke", "match"),
    [
        (
            lambda container: container.add_generator_class(cast("Any", object())),
            "add_generator_class\\(\\) parameter 'generator_class' must be a class",
        ),
        (
            lambda container: container.add_generator_class(_NotFactory),
            "add_generator_class\\(\\) parameter 'generator_class' must define an instance "
            "__call__",
        ),
        (
            lambda container: container.add_generator_class(
                _GeneratorClientFactory,
                require_generator_finally=cast("Any", None),
            ),
            "add_generator_class\\(\\) parameter 'require_generator_finally'",
        ),
        (
            lambda container: container.add_context_manager_class(cast("Any", object())),
            "add_context_manager_class\\(\\) parameter 'context_manager_class' must be a class",
        ),
        (
            lambda container: container.add_context_manager_class(_NotFactory),
            "add_context_manager_class\\(\\) parameter 'context_manager_class' must define "
            "an instance __call__",
        ),
    ],
)
def test_cleanup_factory_class_methods_reject_invalid_arguments(
    invoke: Any,
    match: str,
) -> None:
    container = Container()
    container.add_instance(_Events(values=[]))

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        invoke(container)
