from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from types import TracebackType
from typing import Any, cast

import pytest

from diwire import Container, Lifetime, LockMode, ResolverProtocol, Scope
from diwire._internal.resolvers.assembly.compiler import ResolversAssemblyCompiler
from diwire.exceptions import DIWireAsyncDependencyInSyncContextError, DIWireScopeMismatchError


class _MatrixService:
    def __init__(self) -> None:
        self.value: object | None = None


class _MatrixResource:
    pass


class _MatrixAsyncDependency:
    pass


class _MatrixScopedPair:
    def __init__(self, first: _MatrixService, second: _MatrixService) -> None:
        self.first = first
        self.second = second


class _SignatureService:
    def __init__(self, payload: object) -> None:
        self.payload = payload


class _InlineLeaf:
    pass


class _InlineBranch:
    def __init__(self, left: _InlineLeaf, right: _InlineLeaf) -> None:
        self.left = left
        self.right = right


class _InlineMiddle:
    def __init__(self, branch: _InlineBranch, cached: _MatrixService) -> None:
        self.branch = branch
        self.cached = cached


class _InlineRoot:
    def __init__(self, middle: _InlineMiddle) -> None:
        self.middle = middle


class _InlineManagedMiddle:
    def __init__(self, resource: _MatrixResource) -> None:
        self.resource = resource


class _InlineManagedRoot:
    def __init__(self, middle: _InlineManagedMiddle) -> None:
        self.middle = middle


class _CachedFusionLeafA:
    pass


class _CachedFusionLeafB:
    pass


class _CachedFusionMiddleA:
    def __init__(self, leaf_a: _CachedFusionLeafA, leaf_b: _CachedFusionLeafB) -> None:
        self.leaf_a = leaf_a
        self.leaf_b = leaf_b


class _CachedFusionMiddleB:
    def __init__(self, leaf_a: _CachedFusionLeafA, leaf_b: _CachedFusionLeafB) -> None:
        self.leaf_a = leaf_a
        self.leaf_b = leaf_b


class _CachedFusionRoot:
    def __init__(self, middle_a: _CachedFusionMiddleA, middle_b: _CachedFusionMiddleB) -> None:
        self.middle_a = middle_a
        self.middle_b = middle_b


class _CachedFusionZero:
    pass


class _CachedFusionOne:
    def __init__(self, value: _CachedFusionZero) -> None:
        self.value = value


def _build_resolver_with_cleanup_mode(
    *,
    container: Container,
    cleanup_enabled: bool,
) -> Any:
    return ResolversAssemblyCompiler().build_root_resolver(
        root_scope=Scope.APP,
        registrations=container._providers_registrations,
        cleanup_enabled=cleanup_enabled,
    )


@pytest.mark.parametrize(
    ("provider_kind", "lifetime", "scope", "expect_same", "expect_call_count"),
    [
        ("instance", None, Scope.APP, True, None),
        ("concrete", Lifetime.TRANSIENT, Scope.APP, False, None),
        ("factory", Lifetime.SCOPED, Scope.APP, True, 1),
        ("factory", Lifetime.TRANSIENT, Scope.REQUEST, False, 2),
        ("factory", Lifetime.SCOPED, Scope.REQUEST, True, 1),
    ],
)
def test_assembly_matrix_caching_identity_by_kind_lifetime_scope(
    provider_kind: str,
    lifetime: Lifetime | None,
    scope: Scope,
    expect_same: Any,
    expect_call_count: int | None,
) -> None:
    calls = 0

    def build_service() -> _MatrixService:
        nonlocal calls
        calls += 1
        service = _MatrixService()
        service.value = calls
        return service

    container = Container()
    if provider_kind == "instance":
        instance = _MatrixService()
        instance.value = "instance"
        container.add_instance(instance, provides=_MatrixService)
    elif provider_kind == "concrete":
        assert lifetime is not None
        container.add(
            _MatrixService,
            provides=_MatrixService,
            lifetime=lifetime,
            scope=scope,
        )
    else:
        assert lifetime is not None
        container.add_factory(
            build_service,
            provides=_MatrixService,
            lifetime=lifetime,
            scope=scope,
        )

    if scope is Scope.APP:
        first = container.resolve(_MatrixService)
        second = container.resolve(_MatrixService)
    else:
        with container.enter_scope() as request_scope:
            first = request_scope.resolve(_MatrixService)
            second = request_scope.resolve(_MatrixService)

    assert (first is second) is bool(expect_same)
    if expect_call_count is not None:
        assert calls == expect_call_count


def test_assembly_matrix_scoped_cache_isolated_across_scope_instances() -> None:
    calls = 0

    def build_service() -> _MatrixService:
        nonlocal calls
        calls += 1
        service = _MatrixService()
        service.value = calls
        return service

    container = Container()
    container.add_factory(
        build_service,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as first_scope:
        first = first_scope.resolve(_MatrixService)
        assert first is first_scope.resolve(_MatrixService)

    with container.enter_scope() as second_scope:
        second = second_scope.resolve(_MatrixService)
        assert second is second_scope.resolve(_MatrixService)

    assert first is not second
    assert calls == 2


def test_assembly_matrix_current_scope_dependency_cache_handles_miss_hit_and_isolation() -> None:
    calls = 0

    def build_service() -> _MatrixService:
        nonlocal calls
        calls += 1
        return _MatrixService()

    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(
        build_service,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add(
        _MatrixScopedPair,
        provides=_MatrixScopedPair,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as first_scope:
        first_pair = first_scope.resolve(_MatrixScopedPair)
        next_pair = first_scope.resolve(_MatrixScopedPair)

        assert first_pair is not next_pair
        assert first_pair.first is first_pair.second
        assert next_pair.first is first_pair.first
        assert next_pair.second is first_pair.first

    with container.enter_scope() as second_scope:
        second_pair = second_scope.resolve(_MatrixScopedPair)

        assert second_pair.first is second_pair.second
        assert second_pair.first is not first_pair.first

    assert calls == 2


def test_cached_dispatch_fusion_preserves_dfs_order_identity_and_scope_isolation() -> None:
    events: list[str] = []

    def build_leaf_a() -> _CachedFusionLeafA:
        events.append("leaf_a")
        return _CachedFusionLeafA()

    def build_leaf_b() -> _CachedFusionLeafB:
        events.append("leaf_b")
        return _CachedFusionLeafB()

    def build_middle_a(
        leaf_a: _CachedFusionLeafA,
        leaf_b: _CachedFusionLeafB,
    ) -> _CachedFusionMiddleA:
        events.append("middle_a")
        return _CachedFusionMiddleA(leaf_a, leaf_b)

    def build_middle_b(
        leaf_a: _CachedFusionLeafA,
        leaf_b: _CachedFusionLeafB,
    ) -> _CachedFusionMiddleB:
        events.append("middle_b")
        return _CachedFusionMiddleB(leaf_a, leaf_b)

    def build_root(
        middle_a: _CachedFusionMiddleA,
        middle_b: _CachedFusionMiddleB,
    ) -> _CachedFusionRoot:
        events.append("root")
        return _CachedFusionRoot(middle_a, middle_b)

    container = Container(lock_mode=LockMode.NONE)
    for provider in (build_leaf_a, build_leaf_b, build_middle_a, build_middle_b, build_root):
        container.add_factory(
            provider,
            lifetime=Lifetime.SCOPED,
            scope=Scope.REQUEST,
        )

    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(_CachedFusionRoot)
        assert first_scope.resolve(_CachedFusionRoot) is first
        assert first.middle_a.leaf_a is first.middle_b.leaf_a
        assert first.middle_a.leaf_b is first.middle_b.leaf_b

    assert events == ["leaf_a", "leaf_b", "middle_a", "middle_b", "root"]

    events.clear()
    with container.enter_scope(Scope.REQUEST) as second_scope:
        second = second_scope.resolve(_CachedFusionRoot)

    assert second is not first
    assert second.middle_a.leaf_a is not first.middle_a.leaf_a
    assert events == ["leaf_a", "leaf_b", "middle_a", "middle_b", "root"]


def test_cached_dispatch_fusion_preserves_partial_cache_and_retry_after_failure() -> None:
    events: list[str] = []
    middle_a_values: list[_CachedFusionMiddleA] = []
    middle_b_calls = 0

    def build_leaf_a() -> _CachedFusionLeafA:
        events.append("leaf_a")
        return _CachedFusionLeafA()

    def build_leaf_b() -> _CachedFusionLeafB:
        events.append("leaf_b")
        return _CachedFusionLeafB()

    def build_middle_a(
        leaf_a: _CachedFusionLeafA,
        leaf_b: _CachedFusionLeafB,
    ) -> _CachedFusionMiddleA:
        events.append("middle_a")
        value = _CachedFusionMiddleA(leaf_a, leaf_b)
        middle_a_values.append(value)
        return value

    def build_middle_b(
        leaf_a: _CachedFusionLeafA,
        leaf_b: _CachedFusionLeafB,
    ) -> _CachedFusionMiddleB:
        nonlocal middle_b_calls
        middle_b_calls += 1
        events.append(f"middle_b:{middle_b_calls}")
        if middle_b_calls == 1:
            raise ValueError("middle failure")
        return _CachedFusionMiddleB(leaf_a, leaf_b)

    def build_root(
        middle_a: _CachedFusionMiddleA,
        middle_b: _CachedFusionMiddleB,
    ) -> _CachedFusionRoot:
        events.append("root")
        return _CachedFusionRoot(middle_a, middle_b)

    container = Container(lock_mode=LockMode.NONE)
    for provider in (build_leaf_a, build_leaf_b, build_middle_a, build_middle_b, build_root):
        container.add_factory(provider, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)

    with container.enter_scope(Scope.REQUEST) as scope:
        with pytest.raises(ValueError, match="middle failure"):
            scope.resolve(_CachedFusionRoot)

        assert scope.resolve(_CachedFusionMiddleA) is middle_a_values[0]
        root = scope.resolve(_CachedFusionRoot)
        assert root.middle_a is middle_a_values[0]
        assert scope.resolve(_CachedFusionRoot) is root

    assert events == [
        "leaf_a",
        "leaf_b",
        "middle_a",
        "middle_b:1",
        "middle_b:2",
        "root",
    ]


def test_cached_dispatch_fusion_preserves_reentrant_outer_publication() -> None:
    middle_a_calls = 0
    request_scope: ResolverProtocol | None = None
    nested_values: list[_CachedFusionMiddleA] = []
    outer_values: list[_CachedFusionMiddleA] = []

    def build_leaf_a() -> _CachedFusionLeafA:
        return _CachedFusionLeafA()

    def build_leaf_b() -> _CachedFusionLeafB:
        return _CachedFusionLeafB()

    def build_middle_a(
        leaf_a: _CachedFusionLeafA,
        leaf_b: _CachedFusionLeafB,
    ) -> _CachedFusionMiddleA:
        nonlocal middle_a_calls
        middle_a_calls += 1
        value = _CachedFusionMiddleA(leaf_a, leaf_b)
        if middle_a_calls == 1:
            assert request_scope is not None
            nested_values.append(request_scope.resolve(_CachedFusionMiddleA))
            outer_values.append(value)
        return value

    def build_middle_b(
        leaf_a: _CachedFusionLeafA,
        leaf_b: _CachedFusionLeafB,
    ) -> _CachedFusionMiddleB:
        return _CachedFusionMiddleB(leaf_a, leaf_b)

    def build_root(
        middle_a: _CachedFusionMiddleA,
        middle_b: _CachedFusionMiddleB,
    ) -> _CachedFusionRoot:
        return _CachedFusionRoot(middle_a, middle_b)

    container = Container(lock_mode=LockMode.NONE)
    for provider in (build_leaf_a, build_leaf_b, build_middle_a, build_middle_b, build_root):
        container.add_factory(provider, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)

    with container.enter_scope(Scope.REQUEST) as scope:
        request_scope = scope
        root = scope.resolve(_CachedFusionRoot)

        assert middle_a_calls == 2
        assert nested_values[0] is not outer_values[0]
        assert root.middle_a is outer_values[0]
        assert scope.resolve(_CachedFusionMiddleA) is outer_values[0]


def test_shallow_one_child_cached_dispatch_fusion_preserves_identity_and_scope_isolation() -> None:
    events: list[str] = []

    def build_zero() -> _CachedFusionZero:
        events.append("zero")
        return _CachedFusionZero()

    def build_one(value: _CachedFusionZero) -> _CachedFusionOne:
        events.append("one")
        return _CachedFusionOne(value)

    container = Container(lock_mode=LockMode.NONE)
    for provider in (build_zero, build_one):
        container.add_factory(provider, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)

    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(_CachedFusionOne)

        assert first_scope.resolve(_CachedFusionOne) is first
        assert first_scope.resolve(_CachedFusionZero) is first.value

    with container.enter_scope(Scope.REQUEST) as second_scope:
        second = second_scope.resolve(_CachedFusionOne)

        assert second is not first
        assert second.value is not first.value

    assert events == ["zero", "one", "zero", "one"]


def test_shallow_cached_dispatch_fusion_preserves_failure_and_reentrant_publication() -> None:
    calls = 0
    request_scope: ResolverProtocol | None = None
    nested_values: list[_CachedFusionZero] = []
    outer_values: list[_CachedFusionZero] = []

    def build_value() -> _CachedFusionZero:
        nonlocal calls
        calls += 1
        value = _CachedFusionZero()
        if calls == 1:
            raise ValueError("shallow failure")
        if calls == 2:
            assert request_scope is not None
            nested_values.append(request_scope.resolve(_CachedFusionZero))
            outer_values.append(value)
        return value

    container = Container(lock_mode=LockMode.NONE)
    container.add_factory(build_value, lifetime=Lifetime.SCOPED, scope=Scope.REQUEST)

    with container.enter_scope(Scope.REQUEST) as scope:
        request_scope = scope
        with pytest.raises(ValueError, match="shallow failure"):
            scope.resolve(_CachedFusionZero)

        value = scope.resolve(_CachedFusionZero)

        assert calls == 3
        assert nested_values[0] is not outer_values[0]
        assert value is outer_values[0]
        assert scope.resolve(_CachedFusionZero) is outer_values[0]


def test_assembly_matrix_bounded_transient_inlining_preserves_graph_semantics() -> None:
    events: list[str] = []

    def build_leaf() -> _InlineLeaf:
        events.append("leaf")
        return _InlineLeaf()

    def build_branch(left: _InlineLeaf, right: _InlineLeaf) -> _InlineBranch:
        events.append("branch")
        return _InlineBranch(left, right)

    def build_cached() -> _MatrixService:
        events.append("cached")
        return _MatrixService()

    def build_middle(branch: _InlineBranch, cached: _MatrixService) -> _InlineMiddle:
        events.append("middle")
        return _InlineMiddle(branch, cached)

    def build_root(middle: _InlineMiddle) -> _InlineRoot:
        events.append("root")
        return _InlineRoot(middle)

    container = Container(use_resolver_context=False)
    container.add_factory(
        build_leaf,
        provides=_InlineLeaf,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add_factory(
        build_branch,
        provides=_InlineBranch,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add_factory(
        build_cached,
        provides=_MatrixService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.add_factory(
        build_middle,
        provides=_InlineMiddle,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add_factory(
        build_root,
        provides=_InlineRoot,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        first_leaf = request_scope.resolve(_InlineLeaf)
        request_scope_any = cast("Any", request_scope)
        cached_method = request_scope_any._last_sync_method
        assert request_scope_any._last_sync_dependency is _InlineLeaf

        first = request_scope.resolve(_InlineRoot)
        assert cast("object", request_scope_any._last_sync_dependency) is _InlineRoot
        assert request_scope_any._last_sync_method is cached_method

        second_leaf = request_scope.resolve(_InlineLeaf)
        assert request_scope_any._last_sync_dependency is _InlineLeaf
        refreshed_cached_method = request_scope_any._last_sync_method
        assert refreshed_cached_method is not cached_method

        second = request_scope.resolve(_InlineRoot)
        assert cast("object", request_scope_any._last_sync_dependency) is _InlineRoot
        assert request_scope_any._last_sync_method is refreshed_cached_method

        assert first_leaf is not second_leaf
        assert first is not second
        assert first.middle is not second.middle
        assert first.middle.branch is not second.middle.branch
        assert first.middle.branch.left is not first.middle.branch.right
        assert second.middle.branch.left is not second.middle.branch.right
        assert first.middle.branch.left is not second.middle.branch.left
        assert first.middle.branch.right is not second.middle.branch.right
        assert first.middle.cached is second.middle.cached
        assert events == [
            "leaf",
            "leaf",
            "leaf",
            "branch",
            "cached",
            "middle",
            "root",
            "leaf",
            "leaf",
            "leaf",
            "branch",
            "middle",
            "root",
        ]

    with container.enter_scope(Scope.REQUEST) as next_scope:
        next_value = next_scope.resolve(_InlineRoot)

    assert next_value.middle.cached is not first.middle.cached
    assert events[-6:] == ["leaf", "leaf", "branch", "cached", "middle", "root"]


def test_sync_dispatch_fusion_inlines_sole_scoped_generator_cleanup_graph() -> None:
    def provide_resource() -> Generator[_MatrixResource, None, None]:
        try:
            yield _MatrixResource()
        finally:
            pass

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        resource_slot = container._providers_registrations.get_by_type(
            _MatrixResource,
        ).slot

        assert f"_provider_{resource_slot}" in request_scope.resolve.__code__.co_names
        assert f"resolve_{resource_slot}" not in request_scope.resolve.__code__.co_names
        assert f"aresolve_{resource_slot}" in request_scope.aresolve.__code__.co_names


def test_sync_dispatch_fused_generator_preserves_scope_cache_and_cleanup() -> None:
    events: list[tuple[str, _MatrixResource]] = []

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        resource = _MatrixResource()
        events.append(("enter", resource))
        try:
            yield resource
        finally:
            events.append(("exit", resource))

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as first_scope:
        first = first_scope.resolve(_MatrixResource)
        second = first_scope.resolve(_MatrixResource)
        assert first is second
        assert events == [("enter", first)]

    with container.enter_scope(Scope.REQUEST) as second_scope:
        third = second_scope.resolve(_MatrixResource)
        assert third is not first
        assert events == [("enter", first), ("exit", first), ("enter", third)]

    assert events == [
        ("enter", first),
        ("exit", first),
        ("enter", third),
        ("exit", third),
    ]


def test_sync_dispatch_fused_generator_retries_after_empty_generator() -> None:
    provider_calls = 0
    cleanup_calls = 0

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        nonlocal cleanup_calls, provider_calls
        provider_calls += 1
        if provider_calls == 1:
            return
        try:
            yield _MatrixResource()
        finally:
            cleanup_calls += 1

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        with pytest.raises(RuntimeError, match="generator didn't yield") as error:
            request_scope.resolve(_MatrixResource)

        assert isinstance(error.value.__cause__, StopIteration)
        request_scope_any = cast("Any", request_scope)
        assert request_scope_any._cleanup_callback_single is None
        assert request_scope_any._cleanup_callbacks == []

        resolved = request_scope.resolve(_MatrixResource)
        assert isinstance(resolved, _MatrixResource)
        assert provider_calls == 2

    assert cleanup_calls == 1


def test_sync_dispatch_fused_generator_preserves_disabled_cleanup() -> None:
    cleanup_calls = 0
    retained_generators: list[Generator[_MatrixResource, None, None]] = []

    def resource_generator() -> Generator[_MatrixResource, None, None]:
        nonlocal cleanup_calls
        try:
            yield _MatrixResource()
        finally:
            cleanup_calls += 1

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        provider_generator = resource_generator()
        retained_generators.append(provider_generator)
        return provider_generator

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    root_resolver = _build_resolver_with_cleanup_mode(
        container=container,
        cleanup_enabled=False,
    )

    request_scope = root_resolver.enter_scope(Scope.REQUEST)
    resolved = request_scope.resolve(_MatrixResource)
    request_scope_any = cast("Any", request_scope)
    assert isinstance(resolved, _MatrixResource)
    assert request_scope_any._cleanup_callback_single is None
    assert request_scope_any._cleanup_callbacks == []

    request_scope.__exit__(None, None, None)
    assert cleanup_calls == 0

    retained_generators[0].close()
    assert cleanup_calls == 1


def test_sync_dispatch_fused_generator_preserves_disabled_cleanup_empty_error() -> None:
    provider_calls = 0

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            return
        yield _MatrixResource()

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
        require_generator_finally=False,
    )
    root_resolver = _build_resolver_with_cleanup_mode(
        container=container,
        cleanup_enabled=False,
    )

    request_scope = root_resolver.enter_scope(Scope.REQUEST)
    with pytest.raises(StopIteration):
        request_scope.resolve(_MatrixResource)

    assert isinstance(request_scope.resolve(_MatrixResource), _MatrixResource)
    assert provider_calls == 2
    request_scope.__exit__(None, None, None)


def test_sync_dispatch_fused_generator_preserves_reentrant_outer_publication() -> None:
    events: list[tuple[str, _MatrixResource]] = []
    nested_values: list[_MatrixResource] = []
    request_scope: ResolverProtocol

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        resource = _MatrixResource()
        events.append(("enter", resource))
        if len(events) == 1:
            nested_values.append(request_scope.resolve(_MatrixResource))
        try:
            yield resource
        finally:
            events.append(("exit", resource))

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        outer_value = request_scope.resolve(_MatrixResource)
        cached_value = request_scope.resolve(_MatrixResource)
        assert cached_value is outer_value
        assert len(nested_values) == 1
        assert nested_values[0] is not outer_value
        request_scope_any = cast("Any", request_scope)
        assert request_scope_any._cleanup_callback_single is not None
        assert len(request_scope_any._cleanup_callbacks) == 1
        assert request_scope_any._cleanup_callbacks[0][0] == 2

    assert events == [
        ("enter", outer_value),
        ("enter", nested_values[0]),
        ("exit", nested_values[0]),
        ("exit", outer_value),
    ]


def test_sync_dispatch_fused_generator_retries_after_setup_failure() -> None:
    provider_calls = 0

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            msg = "setup failure"
            raise ValueError(msg)
        try:
            yield _MatrixResource()
        finally:
            pass

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        with pytest.raises(ValueError, match="setup failure"):
            request_scope.resolve(_MatrixResource)

        request_scope_any = cast("Any", request_scope)
        assert request_scope_any._cleanup_callback_single is None
        assert request_scope_any._cleanup_callbacks == []
        assert isinstance(request_scope.resolve(_MatrixResource), _MatrixResource)

    assert provider_calls == 2


def test_sync_dispatch_fused_generator_does_not_displace_cached_factory_fusion() -> None:
    def provide_resource() -> Generator[_MatrixResource, None, None]:
        try:
            yield _MatrixResource()
        finally:
            pass

    container = Container(lock_mode=LockMode.NONE, use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.add(
        _MatrixService,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        resource_slot = container._providers_registrations.get_by_type(
            _MatrixResource,
        ).slot
        service_slot = container._providers_registrations.get_by_type(
            _MatrixService,
        ).slot
        dispatch_names = request_scope.resolve.__code__.co_names

        assert f"_provider_{service_slot}" in dispatch_names
        assert f"resolve_{service_slot}" not in dispatch_names
        assert f"_provider_{resource_slot}" not in dispatch_names
        assert f"resolve_{resource_slot}" in dispatch_names
        assert isinstance(request_scope.resolve(_MatrixResource), _MatrixResource)
        assert isinstance(request_scope.resolve(_MatrixService), _MatrixService)


def test_sync_dispatch_fusion_excludes_scoped_generator_cleanup_graph() -> None:
    events: list[str] = []

    def provide_resource() -> Generator[_MatrixResource, None, None]:
        events.append("enter")
        try:
            yield _MatrixResource()
        finally:
            events.append("exit")

    container = Container(use_resolver_context=False)
    container.add_generator(
        provide_resource,
        provides=_MatrixResource,
        lifetime=Lifetime.SCOPED,
        scope=Scope.REQUEST,
    )
    container.add(
        _InlineManagedMiddle,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add(
        _InlineManagedRoot,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )
    container.add(
        _InlineLeaf,
        lifetime=Lifetime.TRANSIENT,
        scope=Scope.REQUEST,
    )

    with pytest.raises(ValueError, match="body failure"):
        with container.enter_scope(Scope.REQUEST) as request_scope:
            root_slot = container._providers_registrations.get_by_type(
                _InlineManagedRoot,
            ).slot
            assert f"_provider_{root_slot}" not in request_scope.resolve.__code__.co_names
            assert f"resolve_{root_slot}" in request_scope.resolve.__code__.co_names

            first = request_scope.resolve(_InlineManagedRoot)
            second = request_scope.resolve(_InlineManagedRoot)

            assert first is not second
            assert first.middle is not second.middle
            assert first.middle.resource is second.middle.resource
            assert events == ["enter"]
            raise ValueError("body failure")

    assert events == ["enter", "exit"]


@pytest.mark.parametrize("provider_kind", ["generator", "context_manager"])
@pytest.mark.parametrize("cleanup_enabled", [True, False])
def test_assembly_matrix_cleanup_behavior_respects_cleanup_enabled(
    provider_kind: str,
    cleanup_enabled: Any,
) -> None:
    events: list[str] = []
    exit_calls = 0

    def provide_generator() -> Generator[_MatrixResource, None, None]:
        events.append("enter")
        try:
            yield _MatrixResource()
        finally:
            events.append("exit")

    class _ManagedContext:
        def __enter__(self) -> _MatrixResource:
            events.append("enter")
            return _MatrixResource()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            nonlocal exit_calls
            exit_calls += 1
            events.append("exit")

    def provide_context_manager() -> _ManagedContext:
        return _ManagedContext()

    container = Container()
    if provider_kind == "generator":
        container.add_generator(
            provide_generator,
            provides=_MatrixResource,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )
    else:
        container.add_context_manager(
            provide_context_manager,
            provides=_MatrixResource,
            scope=Scope.REQUEST,
            lifetime=Lifetime.SCOPED,
        )

    root_resolver = _build_resolver_with_cleanup_mode(
        container=container,
        cleanup_enabled=bool(cleanup_enabled),
    )
    request_scope = root_resolver.enter_scope()
    resolved = request_scope.resolve(_MatrixResource)

    assert isinstance(resolved, _MatrixResource)
    assert "enter" in events
    expected_callbacks = 1 if bool(cleanup_enabled) else 0
    assert len(request_scope._cleanup_callbacks) == expected_callbacks
    request_scope.__exit__(None, None, None)

    if provider_kind == "context_manager":
        assert exit_calls == expected_callbacks
    elif bool(cleanup_enabled):
        assert "exit" in events


def test_assembly_matrix_scope_mismatch_for_request_scoped_dependency_at_root() -> None:
    container = Container()
    container.add_factory(
        _MatrixService,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with pytest.raises(DIWireScopeMismatchError, match="requires opened scope level"):
        container.resolve(_MatrixService)


@pytest.mark.asyncio
async def test_assembly_matrix_async_dependency_chain_requires_aresolve() -> None:
    async def provide_dependency() -> AsyncGenerator[_MatrixAsyncDependency, None]:
        try:
            yield _MatrixAsyncDependency()
        finally:
            pass

    def build_consumer(dependency: _MatrixAsyncDependency) -> _MatrixService:
        service = _MatrixService()
        service.value = dependency
        return service

    container = Container()
    container.add_generator(
        provide_dependency,
        provides=_MatrixAsyncDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_consumer,
        provides=_MatrixService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        with pytest.raises(
            DIWireAsyncDependencyInSyncContextError,
            match="requires asynchronous resolution",
        ):
            request_scope.resolve(_MatrixService)

    async with container.enter_scope() as request_scope:
        resolved = await request_scope.aresolve(_MatrixService)
        assert isinstance(resolved.value, _MatrixAsyncDependency)


@pytest.mark.parametrize(
    ("lock_mode", "has_thread_lock"),
    [
        (LockMode.THREAD, True),
        (LockMode.NONE, False),
    ],
)
def test_assembly_matrix_cached_sync_path_lock_generation_follows_lock_mode(
    lock_mode: LockMode,
    has_thread_lock: Any,
) -> None:
    calls = 0

    def build_service() -> _MatrixService:
        nonlocal calls
        calls += 1
        return _MatrixService()

    container = Container()
    container.add_factory(
        build_service,
        provides=_MatrixService,
        lifetime=Lifetime.SCOPED,
        lock_mode=lock_mode,
    )
    root_resolver = container.compile()

    first = root_resolver.resolve(_MatrixService)
    second = root_resolver.resolve(_MatrixService)
    assert first is second
    assert calls == 1
    assert bool(has_thread_lock) is (lock_mode is LockMode.THREAD)


@pytest.mark.parametrize("signature_kind", ["positional", "positional_only", "keyword_only"])
def test_assembly_matrix_signature_wiring_for_required_parameters(signature_kind: str) -> None:
    def positional(value: int) -> _SignatureService:
        return _SignatureService(value)

    def positional_only(value: int, /) -> _SignatureService:
        return _SignatureService(value)

    def keyword_only(*, value: int) -> _SignatureService:
        return _SignatureService(value)

    builders: dict[str, Callable[..., _SignatureService]] = {
        "positional": positional,
        "positional_only": positional_only,
        "keyword_only": keyword_only,
    }
    builder = builders[signature_kind]
    signature = inspect.signature(builder)

    container = Container()
    container.add_instance(42, provides=int)
    container.add_factory(
        builder,
        provides=_SignatureService,
        dependencies={
            int: signature.parameters["value"],
        },
    )

    resolved = container.resolve(_SignatureService)

    assert resolved.payload == 42


@pytest.mark.parametrize("signature_kind", ["var_positional", "var_keyword"])
def test_assembly_matrix_signature_wiring_for_variadic_parameters(signature_kind: str) -> None:
    def var_positional(*values: int) -> _SignatureService:
        return _SignatureService(tuple(values))

    def var_keyword(**options: int) -> _SignatureService:
        return _SignatureService(dict(options))

    builders: dict[str, Callable[..., _SignatureService]] = {
        "var_positional": var_positional,
        "var_keyword": var_keyword,
    }
    builder = builders[signature_kind]
    signature = inspect.signature(builder)

    container = Container()
    values_type: Any
    if signature_kind == "var_positional":
        values_type = tuple[int, ...]
        payload: object = (1, 2, 3)
        parameter = signature.parameters["values"]
    else:
        values_type = dict[str, int]
        payload = {"first": 1, "second": 2}
        parameter = signature.parameters["options"]

    container.add_instance(cast("Any", payload), provides=values_type)
    container.add_factory(
        builder,
        provides=_SignatureService,
        dependencies={
            values_type: parameter,
        },
    )

    resolved = container.resolve(_SignatureService)

    assert resolved.payload == payload


@pytest.mark.asyncio
async def test_assembly_matrix_sync_only_graph_has_sync_async_parity() -> None:
    container = Container()
    container.add_factory(
        _sync_only_service,
        provides=_MatrixService,
        lifetime=Lifetime.SCOPED,
    )

    sync_resolved = container.resolve(_MatrixService)
    async_resolved = await container.aresolve(_MatrixService)

    assert sync_resolved is async_resolved
    assert async_resolved.value == "sync-only"


def _sync_only_service() -> _MatrixService:
    service = _MatrixService()
    service.value = "sync-only"
    return service
