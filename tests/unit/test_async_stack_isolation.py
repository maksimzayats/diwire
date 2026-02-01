"""Tests for async resolution stack isolation.

These tests verify that concurrent async tasks properly isolate their resolution stacks
to prevent spurious circular dependency errors in diamond dependency patterns.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from diwire.container import Container
from diwire.exceptions import DIWireCircularDependencyError
from diwire.types import Lifetime

# =============================================================================
# Module-level classes for circular dependency tests
# Forward references require classes to be defined at module level
# =============================================================================


class AsyncCircularA:
    """A -> B (circular)."""

    def __init__(self, b: AsyncCircularB) -> None:
        self.b = b


class AsyncCircularB:
    """B -> A (circular)."""

    def __init__(self, a: AsyncCircularA) -> None:
        self.a = a


class ThreeWayCircularA:
    """A -> B -> C -> A (indirect circular)."""

    def __init__(self, b: ThreeWayCircularB) -> None:
        self.b = b


class ThreeWayCircularB:
    """B -> C."""

    def __init__(self, c: ThreeWayCircularC) -> None:
        self.c = c


class ThreeWayCircularC:
    """C -> A (completes circle)."""

    def __init__(self, a: ThreeWayCircularA) -> None:
        self.a = a


# =============================================================================
# Diamond dependency classes (A -> (B, C) -> D pattern)
# =============================================================================


@dataclass
class DiamondD:
    """Leaf dependency in diamond pattern."""

    id: str = field(default_factory=lambda: "D")


@dataclass
class DiamondB:
    """B depends on D."""

    d: DiamondD


@dataclass
class DiamondC:
    """C depends on D."""

    d: DiamondD


@dataclass
class DiamondA:
    """A depends on B and C (diamond root)."""

    b: DiamondB
    c: DiamondC


# =============================================================================
# Deep diamond with async factory
# =============================================================================


@dataclass
class DeepLeaf:
    """Leaf in deep diamond."""

    id: str = "leaf"


@dataclass
class DeepLeftMid:
    """Left middle layer."""

    leaf: DeepLeaf


@dataclass
class DeepRightMid:
    """Right middle layer."""

    leaf: DeepLeaf


@dataclass
class DeepLeftTop:
    """Left top layer."""

    mid: DeepLeftMid


@dataclass
class DeepRightTop:
    """Right top layer."""

    mid: DeepRightMid


@dataclass
class DeepRoot:
    """Root of deep diamond."""

    left: DeepLeftTop
    right: DeepRightTop


# =============================================================================
# Wide fanout classes (one service with 10 parallel dependencies)
# =============================================================================


@dataclass
class SharedBase:
    """Shared dependency for fanout test."""


@dataclass
class FanoutDep1:
    s: SharedBase


@dataclass
class FanoutDep2:
    s: SharedBase


@dataclass
class FanoutDep3:
    s: SharedBase


@dataclass
class FanoutDep4:
    s: SharedBase


@dataclass
class FanoutDep5:
    s: SharedBase


@dataclass
class FanoutDep6:
    s: SharedBase


@dataclass
class FanoutDep7:
    s: SharedBase


@dataclass
class FanoutDep8:
    s: SharedBase


@dataclass
class FanoutDep9:
    s: SharedBase


@dataclass
class FanoutDep10:
    s: SharedBase


@dataclass
class FanoutRoot:
    """Root with 10 parallel dependencies."""

    d1: FanoutDep1
    d2: FanoutDep2
    d3: FanoutDep3
    d4: FanoutDep4
    d5: FanoutDep5
    d6: FanoutDep6
    d7: FanoutDep7
    d8: FanoutDep8
    d9: FanoutDep9
    d10: FanoutDep10


# =============================================================================
# Concurrent resolution classes
# =============================================================================


@dataclass
class ConcurrentShared:
    """Shared dependency for concurrent tests."""


@dataclass
class ConcurrentServiceA:
    """Service A for concurrent tests."""

    s: ConcurrentShared


@dataclass
class ConcurrentServiceB:
    """Service B for concurrent tests."""

    s: ConcurrentShared


@dataclass
class ConcurrentServiceC:
    """Service C depending on A and B."""

    a: ConcurrentServiceA
    b: ConcurrentServiceB


# =============================================================================
# Nested resolution classes
# =============================================================================


@dataclass
class NestedInner:
    """Inner dependency."""


@dataclass
class NestedMiddle1:
    """Middle layer 1."""

    inner: NestedInner


@dataclass
class NestedMiddle2:
    """Middle layer 2."""

    inner: NestedInner


@dataclass
class NestedOuter1:
    """Outer layer 1."""

    m1: NestedMiddle1
    m2: NestedMiddle2


@dataclass
class NestedOuter2:
    """Outer layer 2."""

    m1: NestedMiddle1
    m2: NestedMiddle2


@dataclass
class NestedRoot:
    """Root of nested structure."""

    o1: NestedOuter1
    o2: NestedOuter2


# =============================================================================
# Singleton diamond classes
# =============================================================================


class SingletonDatabase:
    """Database with instance counter for singleton tests."""

    instance_count = 0

    def __init__(self) -> None:
        SingletonDatabase.instance_count += 1
        self.id = SingletonDatabase.instance_count


@dataclass
class SingletonUserRepo:
    """User repository depending on Database."""

    db: SingletonDatabase


@dataclass
class SingletonProductRepo:
    """Product repository depending on Database."""

    db: SingletonDatabase


@dataclass
class SingletonService:
    """Service depending on both repositories."""

    users: SingletonUserRepo
    products: SingletonProductRepo


# =============================================================================
# Async factory diamond classes
# =============================================================================


@dataclass
class AsyncFactoryConfig:
    """Config for async factory tests."""


@dataclass
class AsyncFactoryDbClient:
    """DB client created by async factory."""

    name: str


@dataclass
class AsyncFactoryCacheClient:
    """Cache client created by async factory."""

    name: str


@dataclass
class AsyncFactoryService:
    """Service using async factory clients."""

    db: AsyncFactoryDbClient
    cache: AsyncFactoryCacheClient


# =============================================================================
# Tests
# =============================================================================


class TestDiamondDependencyNoSpuriousCircularError:
    """Test diamond dependency pattern A -> (B, C) -> D doesn't cause spurious errors."""

    async def test_diamond_dependency_no_spurious_circular_error(
        self,
        container: Container,
    ) -> None:
        """Diamond pattern with shared leaf dependency should resolve without error."""
        result = await container.aresolve(DiamondA)

        assert isinstance(result, DiamondA)
        assert isinstance(result.b, DiamondB)
        assert isinstance(result.c, DiamondC)
        assert isinstance(result.b.d, DiamondD)
        assert isinstance(result.c.d, DiamondD)

    async def test_deep_diamond_with_async_factory(self, container: Container) -> None:
        """Multi-level diamond with async factories should resolve correctly."""

        async def create_leaf() -> DeepLeaf:
            await asyncio.sleep(0.001)
            return DeepLeaf(id="async_leaf")

        container.register(DeepLeaf, factory=create_leaf, lifetime=Lifetime.TRANSIENT)

        result = await container.aresolve(DeepRoot)

        assert isinstance(result, DeepRoot)
        assert isinstance(result.left.mid.leaf, DeepLeaf)
        assert isinstance(result.right.mid.leaf, DeepLeaf)


class TestWideFanoutNoCircularError:
    """Test service with many parallel dependencies doesn't cause spurious errors."""

    async def test_wide_fanout_no_circular_error(self, container: Container) -> None:
        """Service with 10+ parallel dependencies should resolve without error."""
        result = await container.aresolve(FanoutRoot)

        assert isinstance(result, FanoutRoot)
        assert isinstance(result.d1, FanoutDep1)
        assert isinstance(result.d10, FanoutDep10)


class TestRealCircularStillDetected:
    """Test that real circular dependencies are still properly detected."""

    async def test_real_circular_still_detected(self, container: Container) -> None:
        """A -> B -> A circular dependency should still raise error."""
        with pytest.raises(DIWireCircularDependencyError):
            await container.aresolve(AsyncCircularA)

    async def test_three_way_circular_still_detected(self, container: Container) -> None:
        """A -> B -> C -> A circular dependency should still raise error."""
        with pytest.raises(DIWireCircularDependencyError):
            await container.aresolve(ThreeWayCircularA)


class TestConcurrentDiamondResolutions:
    """Test concurrent diamond resolutions don't interfere with each other."""

    async def test_concurrent_diamond_resolutions(self, container: Container) -> None:
        """20 concurrent diamond resolutions should all succeed."""
        tasks = [asyncio.create_task(container.aresolve(DiamondA)) for _ in range(20)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 20
        for result in results:
            assert isinstance(result, DiamondA)
            assert isinstance(result.b, DiamondB)
            assert isinstance(result.c, DiamondC)

    async def test_concurrent_mixed_patterns(self, container: Container) -> None:
        """Concurrent resolutions of different dependency patterns should succeed."""
        tasks: list[asyncio.Task[ConcurrentServiceA | ConcurrentServiceB | ConcurrentServiceC]]
        tasks = []
        for i in range(30):
            if i % 3 == 0:
                tasks.append(asyncio.create_task(container.aresolve(ConcurrentServiceA)))
            elif i % 3 == 1:
                tasks.append(asyncio.create_task(container.aresolve(ConcurrentServiceB)))
            else:
                tasks.append(asyncio.create_task(container.aresolve(ConcurrentServiceC)))

        results = await asyncio.gather(*tasks)

        assert len(results) == 30


class TestStackIsolationNestedResolution:
    """Test stack isolation with nested async resolutions."""

    async def test_stack_isolation_nested_resolution(self, container: Container) -> None:
        """Nested async resolutions with shared dependencies should work correctly."""
        result = await container.aresolve(NestedRoot)

        assert isinstance(result, NestedRoot)
        assert isinstance(result.o1, NestedOuter1)
        assert isinstance(result.o2, NestedOuter2)
        assert isinstance(result.o1.m1.inner, NestedInner)
        assert isinstance(result.o2.m2.inner, NestedInner)

    async def test_async_factory_in_diamond(self, container: Container) -> None:
        """Diamond pattern with async factories at leaf level."""
        call_count = {"db": 0, "cache": 0}

        async def create_db() -> AsyncFactoryDbClient:
            call_count["db"] += 1
            await asyncio.sleep(0.001)
            return AsyncFactoryDbClient(name=f"db_{call_count['db']}")

        async def create_cache() -> AsyncFactoryCacheClient:
            call_count["cache"] += 1
            await asyncio.sleep(0.001)
            return AsyncFactoryCacheClient(name=f"cache_{call_count['cache']}")

        container.register(
            AsyncFactoryDbClient,
            factory=create_db,
            lifetime=Lifetime.TRANSIENT,
        )
        container.register(
            AsyncFactoryCacheClient,
            factory=create_cache,
            lifetime=Lifetime.TRANSIENT,
        )

        result = await container.aresolve(AsyncFactoryService)

        assert result.db.name == "db_1"
        assert result.cache.name == "cache_1"


class TestSingletonWithDiamond:
    """Test singleton lifetime with diamond dependencies."""

    async def test_singleton_diamond_shares_instance(
        self,
        container_singleton: Container,
    ) -> None:
        """Singleton dependencies in diamond pattern should share instance."""
        # Reset counter
        SingletonDatabase.instance_count = 0

        result = await container_singleton.aresolve(SingletonService)

        # Database should only be instantiated once (singleton)
        assert SingletonDatabase.instance_count == 1
        # Both repos should share the same database instance
        assert result.users.db is result.products.db
        assert result.users.db.id == 1
