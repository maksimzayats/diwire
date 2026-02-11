from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, cast

import pytest

from diwire.container import Container
from diwire.container_context import ContainerContext
from diwire.exceptions import DIWireInvalidRegistrationError
from diwire.providers import Lifetime
from diwire.scope import Scope


class _Service:
    pass


def _factory() -> _Service:
    return _Service()


def _generator() -> Generator[_Service, None, None]:
    yield _Service()


@contextmanager
def _context_manager() -> Generator[_Service, None, None]:
    yield _Service()


@pytest.mark.parametrize(
    ("invoke", "match"),
    [
        (
            lambda container: container.add_instance(
                _Service(),
                provides=cast("Any", None),
            ),
            "add_instance\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.add_concrete(_Service, provides=cast("Any", None)),
            "add_concrete\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.add_concrete(cast("Any", None), provides=_Service),
            "add_concrete\\(\\) parameter 'concrete_type'",
        ),
        (
            lambda container: container.add_concrete(
                _Service,
                scope=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.add_concrete(
                _Service,
                lifetime=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.add_concrete(
                _Service,
                dependencies=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.add_concrete(
                _Service,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.add_factory(cast("Any", None)),
            "add_factory\\(\\) parameter 'factory'",
        ),
        (
            lambda container: container.add_factory(_factory, provides=cast("Any", None)),
            "add_factory\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.add_factory(
                _factory,
                scope=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.add_factory(
                _factory,
                lifetime=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.add_factory(
                _factory,
                dependencies=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.add_factory(
                _factory,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.add_generator(cast("Any", None)),
            "add_generator\\(\\) parameter 'generator'",
        ),
        (
            lambda container: container.add_generator(_generator, provides=cast("Any", None)),
            "add_generator\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.add_generator(
                _generator,
                scope=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.add_generator(
                _generator,
                lifetime=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.add_generator(
                _generator,
                dependencies=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.add_generator(
                _generator,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.add_context_manager(
                cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'context_manager'",
        ),
        (
            lambda container: container.add_context_manager(
                _context_manager,
                provides=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.add_context_manager(
                _context_manager,
                scope=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.add_context_manager(
                _context_manager,
                lifetime=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.add_context_manager(
                _context_manager,
                dependencies=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.add_context_manager(
                _context_manager,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.inject(func=cast("Any", None)),
            "inject\\(\\) parameter 'func'",
        ),
        (
            lambda container: container.inject(scope=cast("Any", None)),
            "inject\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.inject(
                autoregister_dependencies=cast("Any", None),
            ),
            "inject\\(\\) parameter 'autoregister_dependencies'",
        ),
    ],
)
def test_container_rejects_none_for_literal_sentinel_parameters(
    invoke: Callable[[Container], Any],
    match: str,
) -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        invoke(container)


@pytest.mark.parametrize(
    ("invoke", "match"),
    [
        (
            lambda context: context.add_instance(
                _Service(),
                provides=cast("Any", None),
            ),
            "add_instance\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.add_concrete(_Service, provides=cast("Any", None)),
            "add_concrete\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.add_concrete(cast("Any", None), provides=_Service),
            "add_concrete\\(\\) parameter 'concrete_type'",
        ),
        (
            lambda context: context.add_concrete(
                _Service,
                scope=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.add_concrete(
                _Service,
                lifetime=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.add_concrete(
                _Service,
                dependencies=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.add_concrete(
                _Service,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_concrete\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.add_factory(cast("Any", None)),
            "add_factory\\(\\) parameter 'factory'",
        ),
        (
            lambda context: context.add_factory(_factory, provides=cast("Any", None)),
            "add_factory\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.add_factory(
                _factory,
                scope=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.add_factory(
                _factory,
                lifetime=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.add_factory(
                _factory,
                dependencies=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.add_factory(
                _factory,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.add_generator(cast("Any", None)),
            "add_generator\\(\\) parameter 'generator'",
        ),
        (
            lambda context: context.add_generator(_generator, provides=cast("Any", None)),
            "add_generator\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.add_generator(
                _generator,
                scope=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.add_generator(
                _generator,
                lifetime=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.add_generator(
                _generator,
                dependencies=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.add_generator(
                _generator,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.add_context_manager(
                cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'context_manager'",
        ),
        (
            lambda context: context.add_context_manager(
                _context_manager,
                provides=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.add_context_manager(
                _context_manager,
                scope=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.add_context_manager(
                _context_manager,
                lifetime=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.add_context_manager(
                _context_manager,
                dependencies=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.add_context_manager(
                _context_manager,
                autoregister_dependencies=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.inject(func=cast("Any", None)),
            "inject\\(\\) parameter 'func'",
        ),
        (
            lambda context: context.inject(scope=cast("Any", None)),
            "inject\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.inject(autoregister_dependencies=cast("Any", None)),
            "inject\\(\\) parameter 'autoregister_dependencies'",
        ),
    ],
)
def test_container_context_rejects_none_for_literal_sentinel_parameters(
    invoke: Callable[[ContainerContext], Any],
    match: str,
) -> None:
    context = ContainerContext()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        invoke(context)


def test_container_context_keeps_infer_dependencies_sentinel() -> None:
    context = ContainerContext()
    context.add_concrete(
        _Service,
        dependencies="infer",
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    operation = context._operations[0]
    assert operation.kwargs["dependencies"] == "infer"


def test_container_add_concrete_decorator_accepts_non_class_provides_key() -> None:
    container = Container()

    decorator = container.add_concrete(provides=cast("Any", "alias"))
    decorator(_Service)

    operation = container._providers_registrations.find_by_type("alias")
    assert operation is not None
    assert operation.concrete_type is _Service


def test_container_context_add_concrete_decorator_accepts_non_class_provides_key() -> None:
    context = ContainerContext()

    decorator = context.add_concrete(provides=cast("Any", "alias"))
    decorator(_Service)

    operation = context._operations[0]
    assert operation.kwargs["provides"] == "alias"
    assert operation.kwargs["concrete_type"] is _Service


def test_container_context_register_instance_accepts_non_class_provides_key() -> None:
    context = ContainerContext()
    context.add_instance(_Service(), provides=cast("Any", "service_key"))

    assert context._operations[0].kwargs["provides"] == "service_key"


def test_container_context_register_concrete_infers_from_class_provides() -> None:
    context = ContainerContext()
    context.add_concrete(_Service)

    operation = context._operations[0]
    assert operation.kwargs["concrete_type"] is _Service


def test_container_context_register_instance_accepts_explicit_provides() -> None:
    context = ContainerContext()
    instance = _Service()

    context.add_instance(instance, provides=_Service)

    operation = context._operations[0]
    assert operation.kwargs["provides"] is _Service


def test_container_context_register_concrete_with_provides_only_uses_infer_concrete() -> None:
    context = ContainerContext()

    decorator = context.add_concrete(provides=_Service)
    decorator(_Service)

    operation = context._operations[0]
    assert operation.kwargs["provides"] is _Service
    assert operation.kwargs["concrete_type"] is _Service
