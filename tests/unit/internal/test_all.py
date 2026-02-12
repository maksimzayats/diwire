from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypeAlias, cast

import pytest

from diwire import All, Component, Container, Injected, Lifetime, Scope
from diwire.exceptions import DIWireInvalidProviderSpecError


class EventHandler(Protocol):
    def handle(self, event: str) -> str: ...


@dataclass(frozen=True, slots=True)
class _Handler:
    name: str

    def handle(self, event: str) -> str:
        return f"{self.name}:{event}"


LoggingHandler: TypeAlias = Annotated[EventHandler, Component("logging")]
MetricsHandler: TypeAlias = Annotated[EventHandler, Component("metrics")]
RequestHandler: TypeAlias = Annotated[EventHandler, Component("request")]


@dataclass(frozen=True, slots=True)
class _Dispatcher:
    handlers: tuple[EventHandler, ...]

    def dispatch(self, event: str) -> tuple[str, ...]:
        return tuple(handler.handle(event) for handler in self.handlers)


@dataclass(frozen=True, slots=True)
class _AllConsumer:
    handlers: tuple[EventHandler, ...]


def test_all_resolves_empty_tuple_when_nothing_registered() -> None:
    container = Container(autoregister_concrete_types=False)

    assert container.resolve(All[EventHandler]) == ()


def test_all_resolves_base_and_components_in_slot_order() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_factory(lambda: _Handler("logging"), provides=LoggingHandler)
    container.add_factory(lambda: _Handler("metrics"), provides=MetricsHandler)
    container.add_factory(lambda: _Handler("base"), provides=EventHandler)

    resolved = container.resolve(All[EventHandler])
    assert tuple(handler.handle("evt") for handler in resolved) == (
        "logging:evt",
        "metrics:evt",
        "base:evt",
    )


def test_inject_can_inject_all_dependency() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(lambda: _Handler("base"), provides=EventHandler)
    container.add_factory(lambda: _Handler("logging"), provides=LoggingHandler)

    @container.inject
    def run(handlers: Injected[All[EventHandler]]) -> tuple[str, ...]:
        return tuple(handler.handle("evt") for handler in handlers)

    assert cast("Any", run)() == ("base:evt", "logging:evt")


def test_provider_dependency_supports_all_dependency() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(lambda: _Handler("logging"), provides=LoggingHandler)
    container.add_factory(lambda: _Handler("base"), provides=EventHandler)

    def build_dispatcher(handlers: All[EventHandler]) -> _Dispatcher:
        return _Dispatcher(handlers=handlers)

    container.add_factory(build_dispatcher, provides=_Dispatcher)

    dispatcher = container.resolve(_Dispatcher)
    assert dispatcher.dispatch("evt") == ("logging:evt", "base:evt")


def test_infer_scope_level_for_injected_all_auto_opens_deeper_scopes() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(lambda: _Handler("base"), provides=EventHandler)
    container.add_factory(
        lambda: _Handler("request"),
        provides=RequestHandler,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @container.inject
    def run(handlers: Injected[All[EventHandler]]) -> tuple[str, ...]:
        return tuple(handler.handle("evt") for handler in handlers)

    assert cast("Any", run)() == ("base:evt", "request:evt")


def test_all_provider_dependency_receives_empty_tuple_when_no_implementations() -> None:
    container = Container(autoregister_concrete_types=False)

    def build_consumer(handlers: All[EventHandler]) -> _AllConsumer:
        return _AllConsumer(handlers=handlers)

    container.add_factory(build_consumer, provides=_AllConsumer)

    consumer = container.resolve(_AllConsumer)
    assert consumer.handlers == ()


def test_infer_dependency_scope_level_for_all_defaults_to_root_when_empty() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = All[EventHandler]
    cache: dict[Any, int] = {}

    inferred = container._infer_dependency_scope_level(
        dependency=dependency,
        cache=cache,
        in_progress=set(),
    )

    assert inferred == Scope.APP.level
    assert cache[dependency] == Scope.APP.level


def test_infer_dependency_scope_level_for_all_handles_components_without_base_registration() -> (
    None
):
    container = Container(autoregister_concrete_types=False)
    container.add_factory(
        lambda: _Handler("request"),
        provides=RequestHandler,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    inferred = container._infer_dependency_scope_level(
        dependency=All[EventHandler],
        cache={},
        in_progress=set(),
    )

    assert inferred == Scope.REQUEST.level


def test_infer_dependency_scope_level_for_all_cycle_guard_returns_root_level() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = All[EventHandler]

    inferred = container._infer_dependency_scope_level(
        dependency=dependency,
        cache={},
        in_progress={dependency},
    )

    assert inferred == Scope.APP.level


def test_all_provider_dependency_is_rejected_for_double_star_kwargs() -> None:
    container = Container(autoregister_concrete_types=False)

    def build_consumer(**handlers: int) -> _AllConsumer:
        _ = handlers
        return _AllConsumer(handlers=())

    signature = inspect.signature(build_consumer)
    container.add_factory(
        build_consumer,
        provides=_AllConsumer,
        dependencies={
            All[EventHandler]: signature.parameters["handlers"],
        },
    )

    with pytest.raises(
        DIWireInvalidProviderSpecError,
        match=r"All\[\.\.\.\] dependencies are not supported for \*\*kwargs parameters",
    ):
        container.compile()


def test_codegen_all_dependency_covers_async_and_inline_root_branches() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(lambda: _Handler("base"), provides=EventHandler)

    async def provide_value() -> int:
        return 1

    container.add_factory(
        provide_value,
        provides=int,
        lifetime=Lifetime.SCOPED,
    )

    def build_consumer(handlers: All[EventHandler], value: int) -> _AllConsumer:
        _ = value
        return _AllConsumer(handlers=handlers)

    container.add_factory(
        build_consumer,
        provides=_AllConsumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    container.compile()
