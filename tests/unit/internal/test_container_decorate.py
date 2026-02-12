from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated, Generic, Protocol, TypeVar

import pytest

from diwire import Component, Container, Lifetime, LockMode, Scope
from diwire._internal.container import (
    _DecorationBaseMetadata,
    _DecorationChain,
    _DecorationRule,
)
from diwire._internal.providers import ProviderSpec
from diwire.exceptions import DIWireInvalidRegistrationError


class _HttpClient(Protocol):
    def get(self, url: str) -> bytes: ...


class _RequestsHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def get(self, url: str) -> bytes:
        return f"{self.base_url}:{url}".encode()


class _Tracer:
    pass


class _TracedHttpClient:
    def __init__(self, inner: _HttpClient, tracer: _Tracer) -> None:
        self.inner = inner
        self.tracer = tracer

    def get(self, url: str) -> bytes:
        return self.inner.get(url)


class _Service:
    pass


class _ServiceImpl(_Service):
    pass


class _FirstLayer(_Service):
    def __init__(self, inner: _Service) -> None:
        self.inner = inner


class _SecondLayer(_Service):
    def __init__(self, inner: _Service) -> None:
        self.inner = inner


class _AmbiguousLayer(_Service):
    def __init__(self, first: _Service, second: _Service) -> None:
        self.first = first
        self.second = second


class _Repo:
    pass


class _PrimaryRepoImpl(_Repo):
    pass


class _RepoDecorator(_Repo):
    def __init__(self, inner: _Repo) -> None:
        self.inner = inner


PrimaryRepo = Annotated[_Repo, Component("primary")]


T = TypeVar("T")


class _IBox(Generic[T]):
    pass


@dataclass(slots=True)
class _Box(_IBox[T]):
    type_arg: type[T]


@dataclass(slots=True)
class _DecoratedBox(_IBox[T]):
    inner: _IBox[T]


def _build_box(type_arg: type[T]) -> _IBox[T]:
    return _Box(type_arg=type_arg)


class _RepoA(_Repo):
    pass


class _RepoB(_Repo):
    pass


class _LockAwareRepoDecorator(_Repo):
    def __init__(self, inner: _Repo) -> None:
        self.inner = inner


async def _build_async_repo() -> _Repo:
    return _RepoA()


async def _decorate_async_repo(inner: _Repo) -> _Repo:
    return _RepoDecorator(inner=inner)


def _invalid_generator_decorator(inner: _Repo) -> Generator[_Repo, None, None]:
    yield inner


def test_decorate_applies_immediately_when_base_binding_already_exists() -> None:
    container = Container()
    container.add_instance("https://api.example.com", provides=str)
    container.add_instance(_Tracer(), provides=_Tracer)
    container.add_concrete(_RequestsHttpClient, provides=_HttpClient)

    container.decorate(provides=_HttpClient, decorator=_TracedHttpClient)

    resolved = container.resolve(_HttpClient)
    assert isinstance(resolved, _TracedHttpClient)
    assert isinstance(resolved.inner, _RequestsHttpClient)
    assert isinstance(resolved.tracer, _Tracer)


def test_decorate_can_be_called_before_base_registration() -> None:
    container = Container()
    container.decorate(provides=_HttpClient, decorator=_TracedHttpClient)
    container.add_instance("https://api.example.com", provides=str)
    container.add_instance(_Tracer(), provides=_Tracer)
    container.add_concrete(_RequestsHttpClient, provides=_HttpClient)

    resolved = container.resolve(_HttpClient)
    assert isinstance(resolved, _TracedHttpClient)
    assert isinstance(resolved.inner, _RequestsHttpClient)


def test_decorators_stack_in_registration_order() -> None:
    container = Container()
    container.add_concrete(_ServiceImpl, provides=_Service)

    container.decorate(provides=_Service, decorator=_FirstLayer)
    container.decorate(provides=_Service, decorator=_SecondLayer)

    resolved = container.resolve(_Service)
    assert isinstance(resolved, _SecondLayer)
    assert isinstance(resolved.inner, _FirstLayer)
    assert isinstance(resolved.inner.inner, _ServiceImpl)


def test_decorate_requires_explicit_inner_parameter_for_ambiguous_decorator() -> None:
    container = Container()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="multiple inner parameter candidates",
    ):
        container.decorate(provides=_Service, decorator=_AmbiguousLayer)

    container.decorate(
        provides=_Service,
        decorator=_AmbiguousLayer,
        inner_parameter="first",
    )


def test_decorate_supports_annotated_keys_with_explicit_inner_parameter() -> None:
    container = Container()
    container.add_concrete(_PrimaryRepoImpl, provides=PrimaryRepo)

    container.decorate(
        provides=PrimaryRepo,
        decorator=_RepoDecorator,
        inner_parameter="inner",
    )

    resolved = container.resolve(PrimaryRepo)
    assert isinstance(resolved, _RepoDecorator)
    assert isinstance(resolved.inner, _PrimaryRepoImpl)


def test_decorate_supports_open_generic_bindings() -> None:
    container = Container()
    container.add_factory(_build_box, provides=_IBox[T])
    container.decorate(provides=_IBox[T], decorator=_DecoratedBox)

    resolved = container.resolve(_IBox[int])
    assert isinstance(resolved, _DecoratedBox)
    assert isinstance(resolved.inner, _Box)
    assert resolved.inner.type_arg is int


def test_decorate_applies_to_later_open_generic_registration() -> None:
    container = Container()
    container.decorate(provides=_IBox[T], decorator=_DecoratedBox)
    container.add_factory(_build_box, provides=_IBox)

    resolved = container.resolve(_IBox[str])
    assert isinstance(resolved, _DecoratedBox)
    assert isinstance(resolved.inner, _Box)
    assert resolved.inner.type_arg is str


def test_re_registering_base_binding_rebuilds_decorator_chain() -> None:
    container = Container()
    container.decorate(provides=_Repo, decorator=_LockAwareRepoDecorator)
    container.add_concrete(_RepoA, provides=_Repo, lock_mode=LockMode.THREAD)

    first = container.resolve(_Repo)
    first_spec = container._providers_registrations.get_by_type(_Repo)

    container.add_concrete(_RepoB, provides=_Repo, lock_mode=LockMode.NONE)

    second = container.resolve(_Repo)
    second_spec = container._providers_registrations.get_by_type(_Repo)

    assert isinstance(first, _LockAwareRepoDecorator)
    assert isinstance(first.inner, _RepoA)
    assert first_spec.lock_mode is LockMode.THREAD
    assert isinstance(second, _LockAwareRepoDecorator)
    assert isinstance(second.inner, _RepoB)
    assert second_spec.lock_mode is LockMode.NONE


@pytest.mark.asyncio
async def test_decorate_supports_async_base_and_async_decorator() -> None:
    container = Container()
    container.add_factory(_build_async_repo, provides=_Repo)
    container.decorate(provides=_Repo, decorator=_decorate_async_repo)

    resolved = await container.aresolve(_Repo)
    assert isinstance(resolved, _RepoDecorator)
    assert isinstance(resolved.inner, _RepoA)


def test_decorate_rejects_generator_decorator() -> None:
    container = Container()

    with pytest.raises(
        DIWireInvalidRegistrationError,
        match="factory-style callable",
    ):
        container.decorate(provides=_Repo, decorator=_invalid_generator_decorator)


def test_decoration_helpers_handle_empty_or_missing_pending_state() -> None:
    container = Container()

    container._apply_pending_decorations(provides=_Repo)
    container._ensure_chain_keys(provides=_Repo)
    container._rebuild_decoration_chain(provides=_Repo)
    assert container._open_generic_registry.find_exact(_Repo) is None


def test_apply_pending_decorations_returns_when_base_binding_is_missing() -> None:
    container = Container()
    container._register_decoration_rule(
        provides=_Repo,
        decorator=_RepoDecorator,
        inner_parameter="inner",
    )

    container._apply_pending_decorations(provides=_Repo)
    assert _Repo not in container._decoration_chain_by_provides


def test_build_decoration_chain_creates_intermediate_layers_for_multiple_rules() -> None:
    container = Container()

    chain = container._build_decoration_chain(provides=_Repo, rule_count=3)

    assert len(chain.layer_keys) == 3
    assert chain.layer_keys[-1] is _Repo


def test_ensure_chain_keys_returns_when_chain_is_already_in_sync() -> None:
    container = Container()
    rule = _DecorationRule(
        decorator=_RepoDecorator,
        inner_parameter="inner",
        dependencies=tuple(
            container._provider_dependencies_extractor.extract_from_factory(_RepoDecorator),
        ),
        is_async=False,
    )
    container._decoration_rules_by_provides[_Repo] = [rule]
    container._decoration_chain_by_provides[_Repo] = _DecorationChain(
        base_key=object(),
        layer_keys=[_Repo],
    )

    container._ensure_chain_keys(provides=_Repo)
    assert len(container._decoration_chain_by_provides[_Repo].layer_keys) == 1


def test_ensure_chain_keys_raises_when_chain_has_more_layers_than_rules() -> None:
    container = Container()
    rule = _DecorationRule(
        decorator=_RepoDecorator,
        inner_parameter="inner",
        dependencies=tuple(
            container._provider_dependencies_extractor.extract_from_factory(_RepoDecorator),
        ),
        is_async=False,
    )
    container._decoration_rules_by_provides[_Repo] = [rule]
    container._decoration_chain_by_provides[_Repo] = _DecorationChain(
        base_key=object(),
        layer_keys=[object(), _Repo],
    )

    with pytest.raises(DIWireInvalidRegistrationError, match="more layers than rules"):
        container._ensure_chain_keys(provides=_Repo)


def test_move_current_binding_to_base_key_raises_for_missing_base_bindings() -> None:
    container = Container()

    with pytest.raises(DIWireInvalidRegistrationError, match="base binding is not registered"):
        container._move_current_binding_to_base_key(provides=_Repo, base_key=object())

    with pytest.raises(DIWireInvalidRegistrationError, match="base open-generic binding"):
        container._move_current_binding_to_base_key(provides=_IBox[T], base_key=object())


def test_rebuild_decoration_chain_handles_missing_rules_and_detects_mismatch() -> None:
    container = Container()
    container._decoration_chain_by_provides[_Repo] = _DecorationChain(
        base_key=object(),
        layer_keys=[_Repo],
    )
    container._rebuild_decoration_chain(provides=_Repo)

    rule = _DecorationRule(
        decorator=_RepoDecorator,
        inner_parameter="inner",
        dependencies=tuple(
            container._provider_dependencies_extractor.extract_from_factory(_RepoDecorator),
        ),
        is_async=False,
    )
    container._decoration_rules_by_provides[_Repo] = [rule]
    container._decoration_chain_by_provides[_Repo] = _DecorationChain(
        base_key=object(),
        layer_keys=[object(), _Repo],
    )

    with pytest.raises(DIWireInvalidRegistrationError, match="out of sync"):
        container._rebuild_decoration_chain(provides=_Repo)


def test_build_decorator_dependencies_raises_when_inner_parameter_is_unknown() -> None:
    container = Container()
    bad_rule = _DecorationRule(
        decorator=_RepoDecorator,
        inner_parameter="unknown",
        dependencies=tuple(
            container._provider_dependencies_extractor.extract_from_factory(_RepoDecorator),
        ),
        is_async=False,
    )

    with pytest.raises(DIWireInvalidRegistrationError, match="unknown inner parameter"):
        container._build_decorator_dependencies(
            rule=bad_rule,
            inner_key=object(),
        )


def test_register_open_generic_decorator_layer_raises_for_non_open_key() -> None:
    container = Container()
    rule = _DecorationRule(
        decorator=_RepoDecorator,
        inner_parameter="inner",
        dependencies=tuple(
            container._provider_dependencies_extractor.extract_from_factory(_RepoDecorator),
        ),
        is_async=False,
    )
    metadata = _DecorationBaseMetadata(
        lifetime=Lifetime.SCOPED,
        scope=Scope.APP,
        lock_mode=LockMode.NONE,
        is_open_generic=True,
    )

    with pytest.raises(DIWireInvalidRegistrationError, match="open-generic decorator layer"):
        container._register_open_generic_decorator_layer(
            provides=_Repo,
            rule=rule,
            dependencies=list(rule.dependencies),
            metadata=metadata,
            is_any_dependency_async=False,
        )


def test_resolve_decoration_base_metadata_raises_for_missing_and_invalid_base_specs() -> None:
    container = Container()
    with pytest.raises(DIWireInvalidRegistrationError, match="base binding") as non_open_error:
        container._resolve_decoration_base_metadata(
            provides=_Repo,
            base_key=object(),
        )
    assert "is missing" in str(non_open_error.value)

    with pytest.raises(DIWireInvalidRegistrationError, match="base binding") as open_error:
        container._resolve_decoration_base_metadata(
            provides=_IBox[T],
            base_key=object(),
        )
    assert "is missing" in str(open_error.value)

    container._providers_registrations.add(
        ProviderSpec(
            provides=_Repo,
            instance=_RepoA(),
            scope=Scope.APP,
            lifetime=None,
            is_async=False,
            is_any_dependency_async=False,
            needs_cleanup=False,
            lock_mode=LockMode.NONE,
        ),
    )
    with pytest.raises(DIWireInvalidRegistrationError, match="has no lifetime"):
        container._resolve_decoration_base_metadata(
            provides=_Repo,
            base_key=_Repo,
        )
