from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, cast

import pytest

from diwire import Container, DependencyRegistrationPolicy, MissingPolicy, ResolverContext
from diwire.exceptions import DIWireInvalidRegistrationError


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
            lambda container: container.add(_Service, provides=cast("Any", None)),
            "add\\(\\) parameter 'provides'",
        ),
        (
            lambda container: container.add(cast("Any", None), provides=_Service),
            "add\\(\\) parameter 'concrete_type'",
        ),
        (
            lambda container: container.add(
                _Service,
                scope=cast("Any", None),
            ),
            "add\\(\\) parameter 'scope'",
        ),
        (
            lambda container: container.add(
                _Service,
                lifetime=cast("Any", None),
            ),
            "add\\(\\) parameter 'lifetime'",
        ),
        (
            lambda container: container.add(
                _Service,
                dependencies=cast("Any", None),
            ),
            "add\\(\\) parameter 'dependencies'",
        ),
        (
            lambda container: container.add(
                _Service,
                dependency_registration_policy=cast("Any", None),
            ),
            "add\\(\\) parameter 'dependency_registration_policy'",
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
                dependency_registration_policy=cast("Any", None),
            ),
            "add_factory\\(\\) parameter 'dependency_registration_policy'",
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
                dependency_registration_policy=cast("Any", None),
            ),
            "add_generator\\(\\) parameter 'dependency_registration_policy'",
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
                dependency_registration_policy=cast("Any", None),
            ),
            "add_context_manager\\(\\) parameter 'dependency_registration_policy'",
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
            lambda context: context.inject(func=cast("Any", None)),
            "inject\\(\\) parameter 'func'",
        ),
        (
            lambda context: context.inject(scope=cast("Any", None)),
            "inject\\(\\) parameter 'scope'",
        ),
        (
            lambda context: context.inject(dependency_registration_policy=cast("Any", None)),
            "inject\\(\\) parameter 'dependency_registration_policy'",
        ),
    ],
)
def test_resolver_context_rejects_none_for_literal_sentinel_parameters(
    invoke: Callable[[ResolverContext], Any],
    match: str,
) -> None:
    context = ResolverContext()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        invoke(context)


def test_container_constructor_rejects_invalid_policy_types() -> None:
    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="Container\\(\\) parameter 'missing_policy'",
    ):
        Container(missing_policy=cast("Any", "error"))

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="Container\\(\\) parameter 'dependency_registration_policy'",
    ):
        Container(dependency_registration_policy=cast("Any", "ignore"))


def test_policy_parameters_accept_enums_and_from_container_literal() -> None:
    container = Container(
        missing_policy=MissingPolicy.ERROR,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )
    container.add(
        _Service,
        dependency_registration_policy=DependencyRegistrationPolicy.IGNORE,
    )
    resolved = container.resolve(_Service, on_missing=MissingPolicy.ERROR)
    assert isinstance(resolved, _Service)

    container.resolve(_Service, on_missing="from_container")
    container.add_factory(
        _factory,
        provides="_service_alias",
        dependency_registration_policy="from_container",
    )
    context = ResolverContext()
    assert callable(context.inject(dependency_registration_policy="from_container"))


def test_container_add_accepts_non_class_provides_key() -> None:
    container = Container()

    container.add(_Service, provides=cast("Any", "alias"))

    operation = container._providers_registrations.find_by_type("alias")
    assert operation is not None
    assert operation.concrete_type is _Service


def test_container_rejects_dependencies_mapping_with_non_parameter_value() -> None:
    container = Container()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="add_factory\\(\\) parameter 'dependencies'",
    ):
        container.add_factory(
            _factory,
            dependencies=cast("Any", {_Service: object()}),
        )


@pytest.mark.parametrize(
    ("invoke", "match"),
    [
        (
            lambda container: container.resolve(
                _Service,
                on_missing=cast("Any", None),
            ),
            "resolve\\(\\) parameter 'on_missing'",
        ),
        (
            lambda container: container.resolve(
                _Service,
                on_missing=cast("Any", "error"),
            ),
            "resolve\\(\\) parameter 'on_missing'",
        ),
    ],
)
def test_container_resolve_rejects_invalid_auto_register_parameters(
    invoke: Callable[[Container], Any],
    match: str,
) -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        invoke(container)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invoke", "match"),
    [
        (
            lambda container: container.aresolve(
                _Service,
                on_missing=cast("Any", None),
            ),
            "aresolve\\(\\) parameter 'on_missing'",
        ),
        (
            lambda container: container.aresolve(
                _Service,
                on_missing=cast("Any", "error"),
            ),
            "aresolve\\(\\) parameter 'on_missing'",
        ),
    ],
)
async def test_container_aresolve_rejects_invalid_auto_register_parameters(
    invoke: Callable[[Container], Any],
    match: str,
) -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match=match):
        await invoke(container)


@pytest.mark.parametrize(
    ("invoke", "match"),
    [
        (
            lambda: cast("Any", Container)(auto_register_on_resolve=False),
            "auto_register_on_resolve",
        ),
        (
            lambda: cast("Any", Container)(auto_register_dependencies=False),
            "auto_register_dependencies",
        ),
        (
            lambda: cast("Any", Container)(autoregister_concrete_types=False),
            "autoregister_concrete_types",
        ),
        (
            lambda: cast("Any", Container)(autoregister_dependencies=False),
            "autoregister_dependencies",
        ),
        (
            lambda: cast("Any", Container)(auto_resolve=False),
            "auto_resolve",
        ),
        (
            lambda: cast("Any", Container)(auto_add_dependencies=False),
            "auto_add_dependencies",
        ),
        (
            lambda: cast("Any", Container()).add(
                _Service,
                register_dependencies=True,
            ),
            "register_dependencies",
        ),
        (
            lambda: cast("Any", Container()).add(
                _Service,
                autoregister_dependencies=True,
            ),
            "autoregister_dependencies",
        ),
        (
            lambda: cast("Any", Container()).add(
                _Service,
                add_dependencies=True,
            ),
            "add_dependencies",
        ),
        (
            lambda: cast("Any", ResolverContext()).inject(register_dependencies=True),
            "register_dependencies",
        ),
        (
            lambda: cast("Any", ResolverContext()).inject(autoregister_dependencies=True),
            "autoregister_dependencies",
        ),
        (
            lambda: cast("Any", ResolverContext()).inject(add_dependencies=True),
            "add_dependencies",
        ),
        (
            lambda: cast("Any", Container()).resolve(_Service, register_if_missing=True),
            "register_if_missing",
        ),
        (
            lambda: cast("Any", Container()).resolve(_Service, register_dependencies=True),
            "register_dependencies",
        ),
        (
            lambda: cast("Any", Container()).resolve(_Service, auto_register_on_missing=True),
            "auto_register_on_missing",
        ),
        (
            lambda: cast("Any", Container()).aresolve(_Service, register_if_missing=True),
            "register_if_missing",
        ),
        (
            lambda: cast("Any", Container()).aresolve(_Service, register_dependencies=True),
            "register_dependencies",
        ),
        (
            lambda: cast("Any", Container()).aresolve(_Service, auto_register_on_missing=True),
            "auto_register_on_missing",
        ),
    ],
)
def test_old_autoregister_keywords_are_rejected(
    invoke: Callable[[], Any],
    match: str,
) -> None:
    with pytest.raises(TypeError, match=match):
        invoke()
