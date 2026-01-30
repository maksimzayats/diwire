"""Tests for circular dependency detection.

Circular dependencies are detected and raise DIWireCircularDependencyError
with a clear message showing the dependency chain.
"""

from __future__ import annotations

import pytest

from diwire.container import Container
from diwire.container_scopes import _current_scope
from diwire.exceptions import DIWireCircularDependencyError
from diwire.types import Lifetime

# Module-level classes for circular dependency tests
# Forward references require classes to be defined at module level


class CircularA:
    """A -> B (circular)."""

    def __init__(self, b: CircularB) -> None:
        self.b = b


class CircularB:
    """B -> A (circular)."""

    def __init__(self, a: CircularA) -> None:
        self.a = a


class SelfRef:
    """Self-referencing class."""

    def __init__(self, other: SelfRef) -> None:
        self.other = other


class ChainA:
    """A -> B -> C -> A (indirect circular)."""

    def __init__(self, b: ChainB) -> None:
        self.b = b


class ChainB:
    """B -> C."""

    def __init__(self, c: ChainC) -> None:
        self.c = c


class ChainC:
    """C -> A (completes circle)."""

    def __init__(self, a: ChainA) -> None:
        self.a = a


class TestCircularDependencies:
    def test_direct_circular_raises_error(self, container: Container) -> None:
        """A -> B -> A raises DIWireCircularDependencyError with clear message."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container.resolve(CircularA)

        assert "CircularA" in str(exc_info.value)
        assert "CircularB" in str(exc_info.value)

    def test_self_referencing_raises_error(self, container: Container) -> None:
        """A -> A raises DIWireCircularDependencyError."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container.resolve(SelfRef)

        assert "SelfRef" in str(exc_info.value)

    def test_indirect_circular_raises_error(self, container: Container) -> None:
        """A -> B -> C -> A raises DIWireCircularDependencyError."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container.resolve(ChainA)

        assert "ChainA" in str(exc_info.value)
        assert "ChainB" in str(exc_info.value)
        assert "ChainC" in str(exc_info.value)

    def test_error_message_shows_full_chain(self, container: Container) -> None:
        """Error message shows complete dependency chain."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container.resolve(ChainA)

        # Should show: ChainA -> ChainB -> ChainC -> ChainA
        error_msg = str(exc_info.value)
        assert "ChainA -> ChainB -> ChainC -> ChainA" in error_msg

    def test_circular_with_kind_singleton(
        self,
        container_singleton: Container,
    ) -> None:
        """Circular dependency with lifetime singleton also raises DIWireCircularDependencyError."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container_singleton.resolve(CircularA)

        assert "CircularA" in str(exc_info.value)
        assert "CircularB" in str(exc_info.value)

    def test_exception_contains_service_key(self, container: Container) -> None:
        """Exception object contains the service key that caused the cycle."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container.resolve(SelfRef)

        assert exc_info.value.service_key is not None
        assert exc_info.value.service_key.value is SelfRef

    def test_exception_contains_resolution_chain(self, container: Container) -> None:
        """Exception object contains the full resolution chain."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            container.resolve(ChainA)

        chain_values = [sk.value for sk in exc_info.value.resolution_chain]
        assert ChainA in chain_values
        assert ChainB in chain_values
        assert ChainC in chain_values


# Module-level classes for scoped circular dependency tests


class ScopedCircularA:
    """Scoped A -> B (circular)."""

    def __init__(self, b: ScopedCircularB) -> None:
        self.b = b


class ScopedCircularB:
    """Scoped B -> A (circular)."""

    def __init__(self, a: ScopedCircularA) -> None:
        self.a = a


class ScopedToSingletonA:
    """Scoped service depending on singleton."""

    def __init__(self, b: ScopedToSingletonB) -> None:
        self.b = b


class ScopedToSingletonB:
    """Singleton depending on scoped (creates circular via mixed lifetimes)."""

    def __init__(self, a: ScopedToSingletonA) -> None:
        self.a = a


class ScopedToTransientA:
    """Scoped service depending on transient."""

    def __init__(self, b: ScopedToTransientB) -> None:
        self.b = b


class ScopedToTransientB:
    """Transient depending on scoped (creates circular via mixed lifetimes)."""

    def __init__(self, a: ScopedToTransientA) -> None:
        self.a = a


class TestScopedCircularDependencies:
    """Tests for circular dependencies involving scoped services."""

    def test_circular_scoped_singletons_raises_error(self, container: Container) -> None:
        """A (scoped) -> B (scoped) -> A raises DIWireCircularDependencyError."""
        container.register(
            ScopedCircularA,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            ScopedCircularB,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            with container.enter_scope("request"):
                container.resolve(ScopedCircularA)

        assert "ScopedCircularA" in str(exc_info.value)
        assert "ScopedCircularB" in str(exc_info.value)

    def test_circular_scoped_and_singleton_mixed(self, container: Container) -> None:
        """Scoped -> Singleton -> Scoped circular raises DIWireCircularDependencyError."""
        container.register(
            ScopedToSingletonA,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(ScopedToSingletonB, lifetime=Lifetime.SINGLETON)

        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            with container.enter_scope("request"):
                container.resolve(ScopedToSingletonA)

        assert "ScopedToSingletonA" in str(exc_info.value)
        assert "ScopedToSingletonB" in str(exc_info.value)

    def test_circular_scoped_and_transient_mixed(self, container: Container) -> None:
        """Scoped -> Transient -> Scoped circular raises DIWireCircularDependencyError."""
        container.register(
            ScopedToTransientA,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(ScopedToTransientB, lifetime=Lifetime.TRANSIENT)

        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            with container.enter_scope("request"):
                container.resolve(ScopedToTransientA)

        assert "ScopedToTransientA" in str(exc_info.value)
        assert "ScopedToTransientB" in str(exc_info.value)

    def test_circular_detection_preserves_scope_context(self, container: Container) -> None:
        """After circular dependency error, scope context is properly cleaned up."""
        container.register(
            ScopedCircularA,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            ScopedCircularB,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        assert _current_scope.get() is None

        try:
            with container.enter_scope("request"):
                container.resolve(ScopedCircularA)
        except DIWireCircularDependencyError:
            pass

        # Scope context should be cleaned up after exception
        assert _current_scope.get() is None


# Module-level classes for async circular dependency tests


class AsyncCircularX:
    """Async X -> Y (circular)."""

    def __init__(self, y: AsyncCircularY) -> None:
        self.y = y


class AsyncCircularY:
    """Async Y -> X (circular)."""

    def __init__(self, x: AsyncCircularX) -> None:
        self.x = x


class TestAsyncCircularDependencies:
    """Tests for circular dependencies detected in aresolve()."""

    async def test_circular_detected_in_aresolve(self, container: Container) -> None:
        """aresolve() detects circular dependencies."""
        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            await container.aresolve(AsyncCircularX)

        assert "AsyncCircularX" in str(exc_info.value)
        assert "AsyncCircularY" in str(exc_info.value)

    async def test_circular_in_async_scope(self, container: Container) -> None:
        """Circular dependency detected in async scope."""
        container.register(
            AsyncCircularX,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            AsyncCircularY,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            async with container.enter_scope("request"):
                await container.aresolve(AsyncCircularX)

        assert "AsyncCircularX" in str(exc_info.value)

    async def test_async_scope_context_preserved_after_circular_error(
        self,
        container: Container,
    ) -> None:
        """Async scope context is cleaned up after circular dependency error."""
        container.register(
            AsyncCircularX,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            AsyncCircularY,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        assert _current_scope.get() is None

        try:
            async with container.enter_scope("request"):
                await container.aresolve(AsyncCircularX)
        except DIWireCircularDependencyError:
            pass

        # Scope context should be cleaned up
        assert _current_scope.get() is None

    async def test_circular_dependency_async_non_compiled(self) -> None:
        """Circular dependency detected in aresolve without compilation.

        This test covers line 1602 in container.py where circular dependency
        is detected in the async non-compiled resolution path.
        To hit this path, we need dependencies to be resolved via aresolve,
        which requires registering them with is_async=True.
        """

        # Define async factories to force async resolution path
        async def create_x(y: AsyncCircularY) -> AsyncCircularX:
            return AsyncCircularX(y)

        async def create_y(x: AsyncCircularX) -> AsyncCircularY:
            return AsyncCircularY(x)

        # Create container without auto-compile and register with async factories
        container = Container(autoregister=False, auto_compile=False)
        container.register(AsyncCircularX, factory=create_x)
        container.register(AsyncCircularY, factory=create_y)

        with pytest.raises(DIWireCircularDependencyError) as exc_info:
            await container.aresolve(AsyncCircularX)

        assert "AsyncCircularX" in str(exc_info.value)
