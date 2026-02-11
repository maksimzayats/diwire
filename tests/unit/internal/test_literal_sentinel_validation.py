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
            lambda container: container.register_instance(
                provides=cast("Any", None),
                instance=_Service(),
            ),
            "register_instance\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.register_concrete(
                provides=cast("Any", None),
                concrete_type=_Service,
            ),
            "register_concrete\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.register_concrete(
                provides=_Service,
                concrete_type=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'concrete_type'",
        ),
        (
            lambda container: container.register_concrete(
                provides=dict[str, int],
            ),
            "register_concrete\\(\\) parameter 'concrete_type' must be provided",
        ),
        (
            lambda container: container.register_concrete(
                concrete_type=_Service,
                scope=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.register_concrete(
                concrete_type=_Service,
                lifetime=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.register_concrete(
                concrete_type=_Service,
                dependencies=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.register_concrete(
                concrete_type=_Service,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.register_factory(factory=cast("Any", None)),
            "register_factory\\(\\) parameter 'factory'",
        ),
        (
            lambda container: container.register_factory(
                provides=cast("Any", None),
                factory=_factory,
            ),
            "register_factory\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.register_factory(
                factory=_factory,
                scope=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.register_factory(
                factory=_factory,
                lifetime=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.register_factory(
                factory=_factory,
                dependencies=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.register_factory(
                factory=_factory,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.register_generator(generator=cast("Any", None)),
            "register_generator\\(\\) parameter 'generator'",
        ),
        (
            lambda container: container.register_generator(
                provides=cast("Any", None),
                generator=_generator,
            ),
            "register_generator\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.register_generator(
                generator=_generator,
                scope=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.register_generator(
                generator=_generator,
                lifetime=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.register_generator(
                generator=_generator,
                dependencies=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.register_generator(
                generator=_generator,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda container: container.register_context_manager(
                context_manager=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'context_manager'",
        ),
        (
            lambda container: container.register_context_manager(
                provides=cast("Any", None),
                context_manager=_context_manager,
            ),
            "register_context_manager\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.register_context_manager(
                context_manager=_context_manager,
                scope=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.register_context_manager(
                context_manager=_context_manager,
                lifetime=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.register_context_manager(
                context_manager=_context_manager,
                dependencies=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.register_context_manager(
                context_manager=_context_manager,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'autoregister_dependencies'",
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
            lambda context: context.register_instance(
                provides=cast("Any", None),
                instance=_Service(),
            ),
            "register_instance\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.register_concrete(
                provides=cast("Any", None),
                concrete_type=_Service,
            ),
            "register_concrete\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.register_concrete(
                provides=_Service,
                concrete_type=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'concrete_type'",
        ),
        (
            lambda context: context.register_concrete(
                provides=dict[str, int],
            ),
            "register_concrete\\(\\) parameter 'concrete_type' must be provided",
        ),
        (
            lambda context: context.register_concrete(
                concrete_type=_Service,
                scope=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.register_concrete(
                concrete_type=_Service,
                lifetime=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.register_concrete(
                concrete_type=_Service,
                dependencies=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.register_concrete(
                concrete_type=_Service,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_concrete\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.register_factory(factory=cast("Any", None)),
            "register_factory\\(\\) parameter 'factory'",
        ),
        (
            lambda context: context.register_factory(
                provides=cast("Any", None),
                factory=_factory,
            ),
            "register_factory\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.register_factory(
                factory=_factory,
                scope=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.register_factory(
                factory=_factory,
                lifetime=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.register_factory(
                factory=_factory,
                dependencies=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.register_factory(
                factory=_factory,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_factory\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.register_generator(generator=cast("Any", None)),
            "register_generator\\(\\) parameter 'generator'",
        ),
        (
            lambda context: context.register_generator(
                provides=cast("Any", None),
                generator=_generator,
            ),
            "register_generator\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.register_generator(
                generator=_generator,
                scope=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.register_generator(
                generator=_generator,
                lifetime=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.register_generator(
                generator=_generator,
                dependencies=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.register_generator(
                generator=_generator,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_generator\\(\\) parameter 'autoregister_dependencies'",
        ),
        (
            lambda context: context.register_context_manager(
                context_manager=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'context_manager'",
        ),
        (
            lambda context: context.register_context_manager(
                provides=cast("Any", None),
                context_manager=_context_manager,
            ),
            "register_context_manager\\(\\) parameter 'provides'",
        ),
        (
            lambda context: context.register_context_manager(
                context_manager=_context_manager,
                scope=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.register_context_manager(
                context_manager=_context_manager,
                lifetime=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'lifetime'",
        ),
        (
            lambda context: context.register_context_manager(
                context_manager=_context_manager,
                dependencies=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'dependencies'",
        ),
        (
            lambda context: context.register_context_manager(
                context_manager=_context_manager,
                autoregister_dependencies=cast("Any", None),
            ),
            "register_context_manager\\(\\) parameter 'autoregister_dependencies'",
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
    context.register_concrete(
        concrete_type=_Service,
        dependencies="infer",
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    operation = context._operations[0]
    assert operation.kwargs["dependencies"] == "infer"


def test_register_concrete_rejects_inferred_concrete_for_non_class_provides() -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match="must be provided when"):
        container.register_concrete(provides=cast("Any", "alias"))


def test_container_context_register_concrete_rejects_inferred_non_class_provides() -> None:
    context = ContainerContext()

    with pytest.raises(DIWireInvalidRegistrationError, match="must be provided when"):
        context.register_concrete(provides=cast("Any", "alias"))


def test_container_context_register_instance_accepts_non_class_provides_key() -> None:
    context = ContainerContext()
    context.register_instance(provides=cast("Any", "service_key"), instance=_Service())

    assert context._operations[0].kwargs["provides"] == "service_key"


def test_container_context_register_concrete_infers_from_class_provides() -> None:
    context = ContainerContext()
    context.register_concrete(provides=_Service)

    operation = context._operations[0]
    assert operation.kwargs["concrete_type"] is _Service


def test_container_context_register_instance_accepts_explicit_provides() -> None:
    context = ContainerContext()
    instance = _Service()

    context.register_instance(provides=_Service, instance=instance)

    operation = context._operations[0]
    assert operation.kwargs["provides"] is _Service


def test_container_context_register_concrete_with_provides_only_uses_infer_concrete() -> None:
    context = ContainerContext()

    context.register_concrete(provides=_Service)

    operation = context._operations[0]
    assert operation.kwargs["provides"] is _Service
    assert operation.kwargs["concrete_type"] is _Service
