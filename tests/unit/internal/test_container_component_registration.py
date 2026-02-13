from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated, Generic, TypeVar

import pytest

from diwire import Component, Container, Lifetime, Scope
from diwire.exceptions import DIWireInvalidRegistrationError


class _Service:
    def __init__(self, value: str) -> None:
        self.value = value


class _ServiceImpl(_Service):
    def __init__(self) -> None:
        super().__init__("impl")


class _Repo:
    pass


class _RepoImpl(_Repo):
    pass


class _RepoDecorator(_Repo):
    def __init__(self, inner: _Repo) -> None:
        self.inner = inner


T = TypeVar("T")


class _GenericValue(Generic[T]):
    def __init__(self, value_type: type[T]) -> None:
        self.value_type = value_type


def test_add_instance_component_registers_component_qualified_key() -> None:
    container = Container()
    expected = _Service("instance")
    marker_expected = _Service("marker")

    container.add_instance(expected, provides=_Service, component="primary")
    container.add_instance(marker_expected, provides=_Service, component=Component("marker"))

    assert container.resolve(Annotated[_Service, Component("primary")]) is expected
    assert container.resolve(Annotated[_Service, Component("marker")]) is marker_expected


def test_add_concrete_component_registers_component_qualified_key() -> None:
    container = Container()
    container.add_concrete(_ServiceImpl, provides=_Service, component="primary")

    resolved = container.resolve(Annotated[_Service, Component("primary")])
    assert isinstance(resolved, _ServiceImpl)


def test_add_factory_infer_form_supports_component() -> None:
    container = Container()

    def _build_direct() -> _Service:
        return _Service("direct")

    def _build_component() -> _Service:
        return _Service("decorator")

    container.add_factory(_build_direct, component="direct")
    container.add_factory(_build_component, component="decorator")

    resolved_direct = container.resolve(Annotated[_Service, Component("direct")])
    resolved_decorator = container.resolve(Annotated[_Service, Component("decorator")])

    assert resolved_direct.value == "direct"
    assert resolved_decorator.value == "decorator"


def test_add_generator_component_registers_and_runs_cleanup() -> None:
    container = Container()
    cleanup_events: list[str] = []

    def _provide() -> Generator[_Service, None, None]:
        try:
            yield _Service("generator")
        finally:
            cleanup_events.append("closed")

    container.add_generator(
        _provide,
        provides=_Service,
        component="request",
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST) as resolver:
        resolved = resolver.resolve(Annotated[_Service, Component("request")])
        assert resolved.value == "generator"

    assert cleanup_events == ["closed"]


def test_add_context_manager_component_registers_and_runs_cleanup() -> None:
    container = Container()
    cleanup_events: list[str] = []

    @contextmanager
    def _provide() -> Generator[_Service, None, None]:
        try:
            yield _Service("context-manager")
        finally:
            cleanup_events.append("closed")

    container.add_context_manager(
        _provide,
        provides=_Service,
        component="request",
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST) as resolver:
        resolved = resolver.resolve(Annotated[_Service, Component("request")])
        assert resolved.value == "context-manager"

    assert cleanup_events == ["closed"]


def test_decorate_with_component_targets_component_qualified_binding() -> None:
    container = Container()
    container.add_concrete(_RepoImpl, provides=_Repo)
    container.add_concrete(_RepoImpl, provides=_Repo, component="primary")

    container.decorate(
        provides=_Repo,
        component="primary",
        decorator=_RepoDecorator,
        inner_parameter="inner",
    )

    base = container.resolve(_Repo)
    component_key = Annotated[_Repo, Component("primary")]
    component_resolved = container.resolve(component_key)

    assert isinstance(base, _RepoImpl)
    assert isinstance(component_resolved, _RepoDecorator)
    assert isinstance(component_resolved.inner, _RepoImpl)


def test_component_appends_to_existing_annotated_provides_metadata() -> None:
    container = Container()
    container.add_instance(
        _Service("annotated"),
        provides=Annotated[_Service, "metadata"],
        component="primary",
    )

    resolved = container.resolve(Annotated[_Service, "metadata", Component("primary")])
    assert resolved.value == "annotated"


def test_component_registration_rejects_already_component_qualified_provides() -> None:
    container = Container()
    component_key = Annotated[_Service, Component("existing")]

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="component-qualified 'provides' key",
    ):
        container.add_factory(lambda: _Service("value"), provides=component_key, component="new")


def test_decorate_rejects_component_when_provides_is_already_component_qualified() -> None:
    container = Container()
    component_key = Annotated[_Repo, Component("existing")]

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="component-qualified 'provides' key",
    ):
        container.decorate(
            provides=component_key,
            component="new",
            decorator=_RepoDecorator,
            inner_parameter="inner",
        )


def test_component_registration_requires_hashable_component_value() -> None:
    container = Container()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="parameter 'component' must be hashable",
    ):
        container.add_instance(_Service("value"), provides=_Service, component=[])

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="parameter 'component' must be hashable",
    ):
        container.add_instance(_Service("value"), provides=_Service, component=Component([]))


def test_closed_generic_typevar_injection_works_with_component_qualified_provides() -> None:
    container = Container()
    container.add_concrete(
        _GenericValue,
        provides=_GenericValue[int],
        component="primary",
    )

    resolved = container.resolve(Annotated[_GenericValue[int], Component("primary")])
    assert resolved.value_type is int
