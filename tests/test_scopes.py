"""Tests for scoped dependency injection."""

import asyncio
import threading
import uuid
from collections.abc import AsyncGenerator, Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Annotated, Any

import pytest

from diwire.container import (
    Container,
    Injected,
    ScopedInjected,
    ScopeId,
    _current_scope,
)
from diwire.exceptions import (
    DIWireGeneratorFactoryWithoutScopeError,
    DIWireMissingDependenciesError,
    DIWireScopedSingletonWithoutScopeError,
    DIWireScopeMismatchError,
    DIWireServiceNotRegisteredError,
)
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import FromDI, Lifetime


@dataclass
class Session:
    """A session with a unique ID for testing scoped singletons."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Service:
    """A service that depends on Session."""

    session: Session


@dataclass
class ServiceA:
    """Service A that depends on Session."""

    session: Session


@dataclass
class ServiceB:
    """Service B that depends on Session."""

    session: Session


class TestLifetimeScopedSingleton:
    """Tests for Lifetime.SCOPED_SINGLETON behavior."""

    def test_scoped_singleton_value(self) -> None:
        """SCOPED_SINGLETON has correct value."""
        assert Lifetime.SCOPED_SINGLETON.value == "scoped_singleton"

    def test_scoped_singleton_without_scope_raises_error(self, container: Container) -> None:
        """SCOPED_SINGLETON without scope raises error at registration time."""
        with pytest.raises(DIWireScopedSingletonWithoutScopeError):
            container.register(Session, lifetime=Lifetime.SCOPED_SINGLETON)

    def test_scoped_singleton_within_scope_shares_instance(self, container: Container) -> None:
        """SCOPED_SINGLETON within scope shares the same instance."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("test"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)

        assert session1.id == session2.id

    def test_scoped_singleton_different_scopes_different_instances(
        self,
        container: Container,
    ) -> None:
        """Different scopes get different SCOPED_SINGLETON instances."""
        container.register(Session, scope="scope1", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Session, scope="scope2", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("scope1"):
            session1 = container.resolve(Session)

        with container.start_scope("scope2"):
            session2 = container.resolve(Session)

        assert session1.id != session2.id


class TestStartScope:
    """Tests for container.start_scope()."""

    def test_start_scope_sets_current_scope(self, container: Container) -> None:
        """start_scope sets the current scope context variable."""
        assert _current_scope.get() is None

        with container.start_scope("test_scope"):
            scope = _current_scope.get()
            assert scope is not None
            assert scope.contains_scope("test_scope")

        assert _current_scope.get() is None

    def test_start_scope_with_auto_generated_name(self, container: Container) -> None:
        """start_scope generates unique ID if no name provided."""
        with container.start_scope() as scoped:
            scope_id = _current_scope.get()
            assert scope_id is not None
            # Should have segments with None name and integer ID
            assert len(scope_id.segments) == 1
            name, instance_id = scope_id.segments[0]
            assert name is None
            assert isinstance(instance_id, int)

    def test_start_scope_cleans_up_scoped_instances(self, container: Container) -> None:
        """Scoped instances are cleaned up when scope exits."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("test"):
            container.resolve(Session)

            # Check that a scope with "test" exists in _scoped_instances
            # Keys are now (scope_segments_tuple, service_key)
            def has_test_scope(
                key: tuple[tuple[tuple[str | None, int], ...], object],
            ) -> bool:
                scope_segments, _ = key
                return any(name == "test" for name, _ in scope_segments)

            assert any(has_test_scope(k) for k in container._scoped_instances)

        # After scope exits, that key should be cleaned up
        assert len(container._scoped_instances) == 0


class TestScopedContainer:
    """Tests for ScopedContainer context manager."""

    def test_scoped_container_resolve(self, container: Container) -> None:
        """ScopedContainer.resolve delegates to container."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("test") as scoped:
            session = scoped.resolve(Session)
            assert isinstance(session, Session)

    def test_scoped_container_nested_scopes(self, container: Container) -> None:
        """Nested scopes create hierarchical scope IDs."""
        with container.start_scope("parent") as parent:
            parent_scope = _current_scope.get()
            assert parent_scope is not None
            assert parent_scope.contains_scope("parent")

            with parent.start_scope("child") as child:
                child_scope = _current_scope.get()
                assert child_scope is not None
                # Child scope should contain parent scope and "child" segment
                assert child_scope.contains_scope("parent")
                assert child_scope.contains_scope("child")
                # Child should have more segments than parent
                assert len(child_scope.segments) == len(parent_scope.segments) + 1

            assert _current_scope.get() == parent_scope

    def test_deeply_nested_scopes(self, container: Container) -> None:
        """Deeply nested scopes maintain hierarchy."""
        with container.start_scope("a") as a, a.start_scope("b") as b:
            with b.start_scope("c") as c:
                scope = _current_scope.get()
                assert scope is not None
                # Check hierarchy: segments contain a, b, c
                assert scope.contains_scope("a")
                assert scope.contains_scope("b")
                assert scope.contains_scope("c")
                assert len(scope.segments) == 3


class TestScopedInjected:
    """Tests for ScopedInjected callable wrapper."""

    def test_resolve_with_scope_returns_scoped_injected(self, container: Container) -> None:
        """resolve() with scope parameter returns ScopedInjected."""

        def handler(service: Annotated[Service, FromDI()]) -> Service:
            return service

        result = container.resolve(handler, scope="request")
        assert isinstance(result, ScopedInjected)

    def test_scoped_injected_shares_instance_within_call(self, container: Container) -> None:
        """ScopedInjected shares scoped instances within a single call."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        def handler(
            service_a: Annotated[ServiceA, FromDI()],
            service_b: Annotated[ServiceB, FromDI()],
        ) -> tuple[ServiceA, ServiceB]:
            return service_a, service_b

        request_handler = container.resolve(handler, scope="request")

        # Services within the same call share the same Session
        a1, b1 = request_handler()
        assert a1.session.id == b1.session.id

        # Subsequent calls get a fresh scope and new Session instance
        a2, b2 = request_handler()
        assert a2.session.id == b2.session.id  # Same within the call
        # Different calls get different sessions (each call creates unique scope)
        assert a1.session.id != a2.session.id

    def test_scoped_injected_preserves_function_name(self, container: Container) -> None:
        """ScopedInjected preserves the wrapped function's name."""

        def my_handler(service: Annotated[Service, FromDI()]) -> None:
            pass

        result = container.resolve(my_handler, scope="request")
        assert result.__name__ == "my_handler"

    def test_scoped_injected_repr(self, container: Container) -> None:
        """ScopedInjected has informative repr."""

        def handler(service: Annotated[Service, FromDI()]) -> None:
            pass

        result = container.resolve(handler, scope="request")
        assert "ScopedInjected" in repr(result)
        assert "request" in repr(result)

    def test_scoped_injected_allows_explicit_kwargs(self, container: Container) -> None:
        """ScopedInjected allows explicit kwargs to override injected ones."""

        def handler(value: int, service: Annotated[Service, FromDI()]) -> tuple[int, Service]:
            return value, service

        request_handler = container.resolve(handler, scope="request")
        custom_service = Service(session=Session(id="custom"))

        result_value, result_service = request_handler(42, service=custom_service)

        assert result_value == 42
        assert result_service.session.id == "custom"


class TestScopeValidation:
    """Tests for scope validation and DIWireScopeMismatchError."""

    def test_scoped_service_not_found_outside_scope(self) -> None:
        """Resolving scoped service outside its scope raises DIWireServiceNotRegisteredError."""
        # With scoped registrations, the registration is only found when scope matches
        container = Container(register_if_missing=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with pytest.raises(DIWireServiceNotRegisteredError), container.start_scope("other_scope"):
            container.resolve(Session)

    def test_scoped_service_not_found_without_scope(self) -> None:
        """Resolving scoped service with no active scope raises DIWireServiceNotRegisteredError."""
        container = Container(register_if_missing=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with pytest.raises(DIWireServiceNotRegisteredError):
            container.resolve(Session)

    def test_scope_mismatch_error_with_global_registration(self) -> None:
        """DIWireScopeMismatchError raised when global registration has scope that doesn't match."""
        # This tests the case where registration is in global registry with scope set
        container = Container(register_if_missing=False)
        service_key = ServiceKey.from_value(Session)
        container._registry[service_key] = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED_SINGLETON,
            scope="request",
        )
        # Set flag since we're bypassing register() which normally sets this
        container._has_scoped_registrations = True

        with pytest.raises(DIWireScopeMismatchError) as exc_info, container.start_scope("wrong"):
            container.resolve(Session)

        error = exc_info.value
        assert error.registered_scope == "request"
        assert error.current_scope is not None
        assert error.current_scope.startswith("wrong/")

    def test_matching_scope_succeeds(self, container: Container) -> None:
        """Resolving in matching scope succeeds."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request"):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_child_scope_can_access_parent_scope_registration(self, container: Container) -> None:
        """Child scopes can resolve services registered for parent scope."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request") as parent, parent.start_scope("child"):
            # Current scope is "request/child" which starts with "request"
            session = container.resolve(Session)
            assert isinstance(session, Session)


class TestScopedRegistration:
    """Tests for per-scope registration."""

    def test_multiple_scoped_registrations(self, container: Container) -> None:
        """Same service can have different registrations for different scopes."""
        container.register(Session, scope="scope_a", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Session, scope="scope_b", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("scope_a"):
            session_a = container.resolve(Session)

        with container.start_scope("scope_b"):
            session_b = container.resolve(Session)

        # Different scopes, different instances
        assert session_a.id != session_b.id

    def test_scoped_registration_independent_of_global(self, container: Container) -> None:
        """Scoped and global registrations work independently."""
        # Scoped registration only
        container.register(Session, scope="special", lifetime=Lifetime.SCOPED_SINGLETON)

        # Inside special scope - uses scoped registration
        with container.start_scope("special"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)
            # Same instance within scope
            assert session1.id == session2.id

        # Different scope instance
        with container.start_scope("special"):
            session3 = container.resolve(Session)
            assert session3.id != session1.id

    def test_most_specific_scope_wins(self, container: Container) -> None:
        """Most specific matching scope registration is used."""
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Session, scope="child", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("parent") as parent:
            session_parent = container.resolve(Session)

            with parent.start_scope("child"):
                # "child" is more specific than "parent"
                session_child = container.resolve(Session)

        # Different registrations, different instances
        assert session_parent.id != session_child.id


class TestScopedInstanceCaching:
    """Tests for scoped instance caching behavior."""

    def test_scoped_instances_cached_at_registration_scope(self, container: Container) -> None:
        """Scoped instances are cached at the registration's scope level."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request") as parent:
            session_parent = container.resolve(Session)

            with parent.start_scope("child"):
                # Should get same instance because cached at "request" level
                session_child = container.resolve(Session)

            # Back in parent scope, same instance
            session_parent2 = container.resolve(Session)

        assert session_parent.id == session_child.id == session_parent2.id

    def test_scoped_instances_isolated_between_scopes(self, container: Container) -> None:
        """Different scope instances don't share scoped singletons."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        sessions = []
        for i in range(3):
            with container.start_scope("request"):
                sessions.append(container.resolve(Session))

        # All different instances
        ids = [s.id for s in sessions]
        assert len(ids) == len(set(ids))


class TestAutoScopeDetection:
    """Tests for automatic scope detection from dependencies."""

    def test_auto_detect_scope_from_global_registration(self, container: Container) -> None:
        """resolve() auto-detects scope from global registration with scope."""
        # Register in global registry with scope (not scoped registry)
        # This is done by registering without scope first, then the _find_scope_in_dependencies
        # checks global registry
        service_key = ServiceKey.from_value(Session)
        container._registry[service_key] = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED_SINGLETON,
            scope="request",
        )

        def handler(
            service_a: Annotated[ServiceA, FromDI()],
            service_b: Annotated[ServiceB, FromDI()],
        ) -> tuple[ServiceA, ServiceB]:
            return service_a, service_b

        # No explicit scope - should auto-detect from Session dependency
        request_handler = container.resolve(handler)

        # Should be ScopedInjected because Session has scope="request"
        assert isinstance(request_handler, ScopedInjected)

    def test_explicit_scope_overrides_auto_detection(self, container: Container) -> None:
        """Explicit scope parameter overrides auto-detection."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        def handler(service: Annotated[Service, FromDI()]) -> Service:
            return service

        # Explicit scope
        result = container.resolve(handler, scope="custom")
        assert isinstance(result, ScopedInjected)

    def test_no_scope_returns_injected(self, container: Container) -> None:
        """Without scoped dependencies, resolve returns regular Injected."""
        container.register(Session, lifetime=Lifetime.TRANSIENT)

        def handler(service: Annotated[Service, FromDI()]) -> Service:
            return service

        result = container.resolve(handler)
        assert isinstance(result, Injected)
        assert not isinstance(result, ScopedInjected)


class TestScopeHierarchyMatching:
    """Tests for scope hierarchy matching logic."""

    def test_exact_scope_match(self, container: Container) -> None:
        """Exact scope name matches."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request"):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_parent_scope_matches_child(self, container: Container) -> None:
        """Parent scope registration matches in child scopes."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request") as parent, parent.start_scope("handler"):
            # "request/handler" contains "request" as parent
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_segment_scope_matches(self, container: Container) -> None:
        """Scope registered as segment matches in hierarchy."""
        container.register(Session, scope="handler", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request") as request, request.start_scope("handler"):
            # "request/handler" contains "handler" as segment
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_non_matching_scope_not_found(self) -> None:
        """Non-matching scope raises DIWireServiceNotRegisteredError."""
        container = Container(register_if_missing=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with pytest.raises(DIWireServiceNotRegisteredError), container.start_scope("other"):
            container.resolve(Session)


class TestScopedInstanceRegistration:
    """Tests for registering instances with specific scopes."""

    def test_scoped_instance_only_returned_in_matching_scope(self, container: Container) -> None:
        """Instance registered with scope should only be returned in that scope."""
        specific_session = Session(id="specific-1234")
        container.register(
            Session,
            instance=specific_session,
            scope="special",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(Session, scope="default", lifetime=Lifetime.SCOPED_SINGLETON)

        # In "special" scope - should return the registered instance
        with container.start_scope("special"):
            session = container.resolve(Session)
            assert session.id == "specific-1234"

        # In "default" scope - should create a new instance (not the specific one)
        with container.start_scope("default"):
            session = container.resolve(Session)
            assert session.id != "specific-1234"

    def test_scoped_instance_not_cached_in_global_singletons(self, container: Container) -> None:
        """Scoped instance should be cached in _scoped_instances, not _singletons."""
        specific_session = Session(id="scoped-instance")
        container.register(
            Session,
            instance=specific_session,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        service_key = ServiceKey.from_value(Session)

        with container.start_scope("test"):
            container.resolve(Session)
            # Should be in scoped instances, not global singletons
            assert service_key not in container._singletons
            # Check that the service is in the scoped instances cache
            # Keys are now (scope_segments, service_key) tuples
            matching_keys = [
                k
                for k in container._scoped_instances
                if any(name == "test" for name, _ in k[0])  # k[0] is scope_segments
            ]
            assert len(matching_keys) == 1
            assert matching_keys[0][1] == service_key  # k[1] is service_key

    def test_different_scopes_different_instances(self, container: Container) -> None:
        """Different scopes can have different registered instances."""
        session_a = Session(id="scope-a-session")
        session_b = Session(id="scope-b-session")

        container.register(
            Session,
            instance=session_a,
            scope="scope_a",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            Session,
            instance=session_b,
            scope="scope_b",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("scope_a"):
            resolved_a = container.resolve(Session)
            assert resolved_a.id == "scope-a-session"

        with container.start_scope("scope_b"):
            resolved_b = container.resolve(Session)
            assert resolved_b.id == "scope-b-session"

    def test_nested_scope_uses_correct_instance(self, container: Container) -> None:
        """Nested scopes should use the instance registered for their specific scope."""
        outer_session = Session(id="outer-session")
        inner_session = Session(id="inner-session")

        container.register(
            Session,
            instance=outer_session,
            scope="outer",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            Session,
            instance=inner_session,
            scope="inner",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("outer") as outer:
            # In outer scope - should return outer instance
            assert container.resolve(Session).id == "outer-session"

            with outer.start_scope("inner"):
                # In inner scope - should return inner instance
                assert container.resolve(Session).id == "inner-session"

            # Back in outer scope - should return outer instance again
            assert container.resolve(Session).id == "outer-session"

    def test_scoped_instance_with_dependent_services(self, container: Container) -> None:
        """Services depending on scoped instance get correct instance per scope."""
        request_session = Session(id="request-session")
        admin_session = Session(id="admin-session")

        container.register(
            Session,
            instance=request_session,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            Session,
            instance=admin_session,
            scope="admin",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("request"):
            service_a = container.resolve(ServiceA)
            service_b = container.resolve(ServiceB)
            assert service_a.session.id == "request-session"
            assert service_b.session.id == "request-session"

        with container.start_scope("admin"):
            service_a = container.resolve(ServiceA)
            service_b = container.resolve(ServiceB)
            assert service_a.session.id == "admin-session"
            assert service_b.session.id == "admin-session"


class TestScopeCleanup:
    """Tests for scope cleanup behavior."""

    def test_nested_scope_cleanup(self, container: Container) -> None:
        """Nested scopes clean up their instances independently."""
        container.register(Session, scope="child", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("parent") as parent:
            with parent.start_scope("child"):
                container.resolve(Session)

                # Check for scope containing "child"
                # Keys are (scope_segments, service_key) tuples
                def has_child_scope(
                    key: tuple[tuple[tuple[str | None, int], ...], object],
                ) -> bool:
                    scope_segments, _ = key
                    return any(name == "child" for name, _ in scope_segments)

                child_scope_keys = [k for k in container._scoped_instances if has_child_scope(k)]
                assert len(child_scope_keys) == 1

            # Child scope cleaned up
            child_scope_keys = [k for k in container._scoped_instances if has_child_scope(k)]
            assert len(child_scope_keys) == 0

    def test_scope_cleanup_on_exception(self, container: Container) -> None:
        """Scopes clean up even when exceptions occur."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        try:
            with container.start_scope("test"):
                container.resolve(Session)
                raise ValueError("Test exception")
        except ValueError:
            pass

        assert len(container._scoped_instances) == 0
        assert _current_scope.get() is None


class TestCaptiveDependency:
    """Tests for captive dependency scenarios (singleton capturing scoped).

    References:
    - https://blog.ploeh.dk/2014/06/02/captive-dependency/
    - https://blog.markvincze.com/two-gotchas-with-scoped-and-singleton-dependencies-in-asp-net-core/
    """

    def test_singleton_capturing_scoped_dependency(self, container: Container) -> None:
        """Singleton that depends on scoped service captures the scoped instance.

        This is a known anti-pattern (captive dependency). The scoped Session
        gets captured by the singleton and lives forever.
        """

        @dataclass
        class SingletonService:
            session: Session  # This will be captured!

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(SingletonService, lifetime=Lifetime.SINGLETON)

        # First request scope
        with container.start_scope("request"):
            singleton1 = container.resolve(SingletonService)
            captured_session_id = singleton1.session.id

        # Second request scope - the singleton still has the old session!
        with container.start_scope("request"):
            singleton2 = container.resolve(SingletonService)
            # This demonstrates the captive dependency problem
            assert singleton2.session.id == captured_session_id
            assert singleton1 is singleton2

    def test_transient_depending_on_scoped_gets_same_instance_within_scope(
        self,
        container: Container,
    ) -> None:
        """Transient services depending on scoped get same scoped instance within scope."""

        @dataclass
        class TransientService:
            session: Session

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(TransientService, lifetime=Lifetime.TRANSIENT)

        with container.start_scope("request"):
            t1 = container.resolve(TransientService)
            t2 = container.resolve(TransientService)
            # Different transient instances
            assert t1 is not t2
            # But same scoped session
            assert t1.session.id == t2.session.id


class TestScopeEdgeCases:
    """Tests for edge cases in scope handling."""

    def test_scope_name_with_slash_character(self, container: Container) -> None:
        """Scope names containing '/' may cause hierarchy parsing issues."""
        container.register(Session, scope="my/scope", lifetime=Lifetime.SCOPED_SINGLETON)

        # This might break the hierarchy parsing since "/" is used as separator
        with container.start_scope("my/scope"):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_empty_scope_name(self, container: Container) -> None:
        """Empty string as scope name."""
        container.register(Session, scope="", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope(""):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_reenter_same_scope_name(self, container: Container) -> None:
        """Re-entering a scope with the same name creates fresh instances."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request"):
            session1 = container.resolve(Session)

        # Re-enter with same name - should be a fresh scope
        with container.start_scope("request"):
            session2 = container.resolve(Session)

        assert session1.id != session2.id

    def test_resolve_container_within_scope(self, container: Container) -> None:
        """Resolving Container within different scopes returns same instance."""
        with container.start_scope("scope1"):
            c1 = container.resolve(Container)

        with container.start_scope("scope2"):
            c2 = container.resolve(Container)

        assert c1 is c2
        assert c1 is container

    def test_factory_with_scope(self, container: Container) -> None:
        """Factory registered with scope creates instances per scope."""

        class SessionFactory:
            def __call__(self) -> Session:
                return Session(id="factory-created")

        container.register(
            Session,
            factory=SessionFactory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("request"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)
            assert session1.id == "factory-created"
            assert session1 is session2

    def test_overwrite_scoped_registration(self, container: Container) -> None:
        """Registering same service twice for same scope overwrites."""
        container.register(
            Session,
            instance=Session(id="first"),
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            Session,
            instance=Session(id="second"),
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("test"):
            session = container.resolve(Session)
            assert session.id == "second"

    def test_resolve_after_scope_exits_via_stale_scoped_container(
        self,
        container: Container,
    ) -> None:
        """Resolving via stale ScopedContainer after scope exits."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("test") as scoped:
            session_inside = scoped.resolve(Session)

        # The scope has exited, but we still have reference to scoped container
        # This resolves using the container but scope context is gone
        with pytest.raises((DIWireScopeMismatchError, DIWireServiceNotRegisteredError)):  # type: ignore[no-matching-overload]
            scoped.resolve(Session)

    def test_concurrent_scope_same_name_different_instances(self, container: Container) -> None:
        """Concurrent scopes with same name should be isolated."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        results: dict[str, str] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                with container.start_scope("request"):
                    session = container.resolve(Session)
                    results[worker_id] = session.id
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors occurred: {errors}"
        # Each worker should have gotten a different session (different scope instances)
        session_ids = list(results.values())
        assert len(session_ids) == len(set(session_ids)), "Sessions should be unique per scope"


class TestGlobalVsScopedRegistration:
    """Tests for interactions between global and scoped registrations."""

    def test_global_singleton_and_scoped_singleton_same_type(self, container: Container) -> None:
        """When both global singleton and scoped singleton exist for same type."""
        # Register global singleton
        global_session = Session(id="global")
        container.register(Session, instance=global_session, lifetime=Lifetime.SINGLETON)

        # Also register scoped
        container.register(
            Session,
            instance=Session(id="scoped"),
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        # Outside scope - should get global
        session_outside = container.resolve(Session)
        assert session_outside.id == "global"

        with container.start_scope("request"):
            session_inside = container.resolve(Session)
            # Scoped registration should take precedence
            assert session_inside.id == "scoped"

    def test_global_transient_with_scoped_fallback(self, container: Container) -> None:
        """Global transient registration with scoped registration for specific scope."""
        container.register(Session, lifetime=Lifetime.TRANSIENT)
        container.register(
            Session,
            instance=Session(id="special-scoped"),
            scope="special",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        # Outside special scope - uses global transient
        s1 = container.resolve(Session)
        s2 = container.resolve(Session)
        assert s1 is not s2  # Transient creates new instances

        # Inside special scope - uses scoped instance
        with container.start_scope("special"):
            s3 = container.resolve(Session)
            s4 = container.resolve(Session)
            assert s3.id == "special-scoped"
            assert s3 is s4  # Same scoped instance


class TestScopeWithDependencyChains:
    """Tests for scoped services in dependency chains."""

    def test_deep_dependency_chain_with_scoped_service(self, container: Container) -> None:
        """Scoped service deep in dependency chain should be shared."""

        @dataclass
        class Level3:
            session: Session

        @dataclass
        class Level2:
            level3: Level3

        @dataclass
        class Level1:
            level2: Level2
            session: Session  # Also depends on Session directly

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request"):
            level1 = container.resolve(Level1)
            # Session should be shared across all levels
            assert level1.session.id == level1.level2.level3.session.id

    def test_mixed_lifetimes_in_chain(self, container: Container) -> None:
        """Chain with mixed singleton, transient, and scoped lifetimes."""

        @dataclass
        class TransientDep:
            session: Session

        @dataclass
        class SingletonDep:
            transient: TransientDep

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(TransientDep, lifetime=Lifetime.TRANSIENT)
        container.register(SingletonDep, lifetime=Lifetime.SINGLETON)

        with container.start_scope("request"):
            singleton1 = container.resolve(SingletonDep)
            captured_session_id = singleton1.transient.session.id

        with container.start_scope("request"):
            singleton2 = container.resolve(SingletonDep)
            # Singleton captured the transient which captured the scoped session
            assert singleton2.transient.session.id == captured_session_id


class TestScopeContextVariableIsolation:
    """Tests for context variable isolation across threads/async."""

    def test_scope_context_isolated_between_threads(self, container: Container) -> None:
        """Each thread should have its own scope context."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        scope_values: dict[str, Any] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                # Check scope is None initially
                scope_values[f"{worker_id}_before"] = _current_scope.get()

                with container.start_scope(f"scope-{worker_id}"):
                    scope_values[f"{worker_id}_inside"] = _current_scope.get()
                    import time

                    time.sleep(0.01)  # Small delay to interleave threads

                scope_values[f"{worker_id}_after"] = _current_scope.get()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

        # Each thread should have had None before and after
        for i in range(3):
            assert scope_values[f"t{i}_before"] is None
            inside_scope = scope_values[f"t{i}_inside"]
            assert inside_scope is not None
            assert inside_scope.contains_scope(f"scope-t{i}")
            assert scope_values[f"t{i}_after"] is None

    def test_async_scope_isolation(self, container: Container) -> None:
        """Async tasks should have isolated scope contexts."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        results: dict[str, str] = {}

        async def async_worker(worker_id: str) -> None:
            with container.start_scope("request"):
                session = container.resolve(Session)
                results[worker_id] = session.id
                await asyncio.sleep(0.01)  # Allow interleaving

        async def run_workers() -> None:
            await asyncio.gather(*[async_worker(f"task-{i}") for i in range(5)])

        asyncio.run(run_workers())

        # Each async task should have gotten different session
        session_ids = list(results.values())
        assert len(session_ids) == len(set(session_ids))


# ============================================================================
# Transitive Scope Dependencies Tests
# ============================================================================


@dataclass
class ScopedLevel1:
    """Level 1 service depending on Level 2."""

    level2: "ScopedLevel2"


@dataclass
class ScopedLevel2:
    """Level 2 service depending on Level 3."""

    level3: "ScopedLevel3"


@dataclass
class ScopedLevel3:
    """Level 3 service depending on Session."""

    session: Session


@dataclass
class ScopedLevel4:
    """Level 4 service depending on Level 5."""

    level5: "ScopedLevel5"


@dataclass
class ScopedLevel5:
    """Level 5 service (bottom of chain)."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


# Module-level classes for long transitive chain test
@dataclass
class ChainA:
    """Chain A depending on B."""

    b: "ChainB"


@dataclass
class ChainB:
    """Chain B depending on C."""

    c: "ChainC"


@dataclass
class ChainC:
    """Chain C depending on D."""

    d: "ChainD"


@dataclass
class ChainD:
    """Chain D depending on E."""

    e: "ChainE"


@dataclass
class ChainE:
    """Chain E depending on Session (bottom of chain)."""

    session: Session


# Module-level classes for transitive scope outside scope test
@dataclass
class OuterService:
    """Outer service depending on inner."""

    inner: "InnerService"


@dataclass
class InnerService:
    """Inner scoped service."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


# Module-level classes for captive dependency tests
@dataclass
class OuterScopedService:
    """Outer scoped service depending on inner."""

    inner: "InnerScopedService"


@dataclass
class InnerScopedService:
    """Inner scoped service."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SingletonTop:
    """Singleton top service depending on transient middle."""

    transient: "TransientMiddle"


@dataclass
class TransientMiddle:
    """Transient middle service depending on session."""

    session: Session


class TestTransitiveScopeDependencies:
    """Tests for transitive scope dependencies."""

    def test_scoped_depends_on_scoped_same_scope(self, container: Container) -> None:
        """A->B->C all scoped:request shares same instances within scope."""
        container.register(ScopedLevel1, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ScopedLevel2, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ScopedLevel3, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request"):
            level1_a = container.resolve(ScopedLevel1)
            level1_b = container.resolve(ScopedLevel1)
            level3_direct = container.resolve(ScopedLevel3)
            session_direct = container.resolve(Session)

            # Same instances due to scoped singleton
            assert level1_a is level1_b
            assert level1_a.level2.level3 is level3_direct
            assert level1_a.level2.level3.session is session_direct

    def test_scoped_depends_on_scoped_different_scope(self, container: Container) -> None:
        """A (outer) -> B (inner) resolved in correct scopes."""
        container.register(ScopedLevel2, scope="outer", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ScopedLevel3, scope="inner", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Session, scope="inner", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("outer") as outer:
            with outer.start_scope("inner"):
                level2 = container.resolve(ScopedLevel2)
                assert isinstance(level2, ScopedLevel2)
                assert isinstance(level2.level3.session, Session)

    def test_long_transitive_chain_all_scoped(self, container: Container) -> None:
        """5+ scoped services in chain: bottom service is shared."""
        container.register(ChainA, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ChainB, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ChainC, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ChainD, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(ChainE, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("request"):
            chain_a = container.resolve(ChainA)
            session_direct = container.resolve(Session)

            # Bottom service Session should be shared
            assert chain_a.b.c.d.e.session is session_direct

    def test_transitive_scoped_resolved_outside_scope(self) -> None:
        """A -> B(scoped:special) resolved outside scope raises error."""
        container = Container(register_if_missing=False)

        container.register(OuterService, lifetime=Lifetime.TRANSIENT)
        container.register(InnerService, scope="special", lifetime=Lifetime.SCOPED_SINGLETON)

        # Outside scope, should fail because InnerService requires "special" scope
        # The error type depends on how the container handles it:
        # - DIWireMissingDependenciesError: when scoped dep can't be resolved without scope
        # - DIWireScopeMismatchError: when scope check explicitly fails
        # - DIWireServiceNotRegisteredError: when no registration found
        with pytest.raises(  # type: ignore[call-overload]
            (
                DIWireMissingDependenciesError,
                DIWireScopeMismatchError,
                DIWireServiceNotRegisteredError,
            ),
        ):
            container.resolve(OuterService)


# ============================================================================
# Factory Edge Cases with Scopes
# ============================================================================


class TestFactoryEdgeCasesWithScopes:
    """Tests for factory edge cases with scopes."""

    def test_factory_exception_within_scope_no_instance_cached(
        self,
        container: Container,
    ) -> None:
        """Factory throws, then succeeds: no corrupted state."""
        call_count = 0

        class FailingFactory:
            def __call__(self) -> Session:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ValueError("First call fails")
                return Session(id="success")

        container.register(
            Session,
            factory=FailingFactory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("request"):
            # First call should fail
            with pytest.raises(ValueError, match="First call fails"):
                container.resolve(Session)

            # Second call should succeed (no corrupted state)
            session = container.resolve(Session)
            assert session.id == "success"

    def test_factory_exception_cleanup_in_nested_scope(self, container: Container) -> None:
        """Factory error in nested scope: parent unaffected."""
        parent_session = Session(id="parent-session")

        class FailingChildFactory:
            def __call__(self) -> Session:
                raise ValueError("Child factory fails")

        container.register(
            Session,
            instance=parent_session,
            scope="parent",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            Session,
            factory=FailingChildFactory,
            scope="child",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("parent") as parent:
            # Parent scope works
            session_in_parent = container.resolve(Session)
            assert session_in_parent.id == "parent-session"

            try:
                with parent.start_scope("child"):
                    container.resolve(Session)
            except ValueError:
                pass

            # Parent still works after child failure
            session_after_failure = container.resolve(Session)
            assert session_after_failure.id == "parent-session"

    def test_factory_accessing_container_within_scope(self, container: Container) -> None:
        """Factory resolves other services within scope: works correctly."""

        @dataclass
        class Config:
            value: str = "config-value"

        class ServiceWithConfigFactory:
            def __init__(self, container: Container) -> None:
                self._container = container

            def __call__(self) -> Service:
                config = self._container.resolve(Config)
                return Service(session=Session(id=config.value))

        container.register(Config, lifetime=Lifetime.SINGLETON)
        container.register(
            Service,
            factory=ServiceWithConfigFactory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("request"):
            service = container.resolve(Service)
            assert service.session.id == "config-value"

    def test_factory_per_scope_returns_different_instances(self, container: Container) -> None:
        """Factory called once per scope: different instances per scope."""
        factory_calls = []

        class TrackingFactory:
            def __call__(self) -> Session:
                session = Session()
                factory_calls.append(session.id)
                return session

        container.register(
            Session,
            factory=TrackingFactory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        sessions = []
        for _ in range(3):
            with container.start_scope("request"):
                sessions.append(container.resolve(Session))

        # Each scope should have called factory once
        assert len(factory_calls) == 3
        # All sessions should be different
        assert len({s.id for s in sessions}) == 3

    def test_generator_factory_closes_on_scope_exit(self, container: Container) -> None:
        """Generator factory yields instance and closes on scope exit."""
        cleanup_events: list[str] = []

        def session_factory() -> Generator[Session, None, None]:
            try:
                yield Session(id="generated")
            finally:
                cleanup_events.append("closed")

        container.register(
            Session,
            factory=session_factory,
            scope="request",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("request"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)
            assert session1 is session2
            assert session1.id == "generated"
            assert cleanup_events == []

        assert cleanup_events == ["closed"]

    def test_generator_factory_without_scope_raises(self, container: Container) -> None:
        """Generator factory requires an active scope."""

        def session_factory() -> Generator[Session, None, None]:
            yield Session(id="generated")

        container.register(Session, factory=session_factory, lifetime=Lifetime.TRANSIENT)

        with pytest.raises(DIWireGeneratorFactoryWithoutScopeError):
            container.resolve(Session)

    def test_generator_factories_close_in_nested_scopes(self, container: Container) -> None:
        """Nested scopes close generator factories in the right order."""
        cleanup_events: list[str] = []

        def parent_factory() -> Generator[Session, None, None]:
            try:
                yield Session(id="parent")
            finally:
                cleanup_events.append("parent")

        def child_factory() -> Generator[Session, None, None]:
            try:
                yield Session(id="child")
            finally:
                cleanup_events.append("child")

        container.register(
            Session,
            factory=parent_factory,
            scope="parent",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )
        container.register(
            Session,
            factory=child_factory,
            scope="child",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with container.start_scope("parent") as parent:
            parent_session = container.resolve(Session)
            assert parent_session.id == "parent"
            assert cleanup_events == []

            with parent.start_scope("child"):
                child_session = container.resolve(Session)
                assert child_session.id == "child"
                assert cleanup_events == []

            assert cleanup_events == ["child"]

        assert cleanup_events == ["child", "parent"]


# ============================================================================
# Scope Error Recovery Tests
# ============================================================================


class TestScopeErrorRecovery:
    """Tests for scope error recovery scenarios."""

    def test_partial_scope_cleanup_when_nested_fails(self, container: Container) -> None:
        """Nested scope fails: parent preserved."""
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("parent") as parent:
            parent_session = container.resolve(Session)

            try:
                with parent.start_scope("child"):
                    raise ValueError("Child scope error")
            except ValueError:
                pass

            # Parent session still accessible and same instance
            session_after_error = container.resolve(Session)
            assert session_after_error is parent_session

    def test_exception_in_scope_exit_still_resets_context(self, container: Container) -> None:
        """Exception during scope exit: context still reset."""
        assert _current_scope.get() is None

        # We can't easily make clear_scope raise without modifying the container
        # So we test that normal exception handling still cleans up context
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        try:
            with container.start_scope("test"):
                container.resolve(Session)
                raise RuntimeError("Error during scope")
        except RuntimeError:
            pass

        assert _current_scope.get() is None

    def test_resolve_from_manually_cleared_scope(self, container: Container) -> None:
        """Manual clear_scope then resolve: creates new instance (cache cleared)."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("test") as scoped:
            session1 = container.resolve(Session)
            scope_id = _current_scope.get()

            # Manually clear the scope (unusual operation)
            container.clear_scope(scope_id)  # type: ignore[arg-type]

            # After clearing, a new instance is created (cache was emptied)
            session2 = container.resolve(Session)
            assert session1.id != session2.id

    def test_double_exit_scope_idempotent(self, container: Container) -> None:
        """__exit__ called twice: clear_scope on already-cleared scope is safe."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        # Use the context manager normally
        with container.start_scope("test") as scoped:
            container.resolve(Session)
            scope_id = scoped._scope_id

        # The scope should be cleared after normal exit
        # Check that no keys have matching scope segments
        assert not any(k[0] == scope_id.segments for k in container._scoped_instances)

        # Manually calling clear_scope again should be idempotent (no error)
        container.clear_scope(scope_id)

        # Still no error and scope context is None
        assert _current_scope.get() is None


# ============================================================================
# Concurrent Scope Edge Cases
# ============================================================================


class TestConcurrentScopeEdgeCases:
    """Tests for concurrent scope edge cases."""

    def test_same_scope_name_concurrent_threads_isolated(self, container: Container) -> None:
        """Multiple threads, same scope name: complete isolation."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        results: dict[str, str] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                with container.start_scope("request"):
                    session = container.resolve(Session)
                    results[worker_id] = session.id
                    # Simulate some work
                    import time

                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, f"worker-{i}") for i in range(10)]
            for f in futures:
                f.result()

        assert not errors
        # All workers should have unique sessions
        session_ids = list(results.values())
        assert len(session_ids) == len(set(session_ids))

    def test_scope_hierarchy_consistency_concurrent(self, container: Container) -> None:
        """Concurrent nested scope creation: hierarchy intact."""
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(Service, scope="child", lifetime=Lifetime.SCOPED_SINGLETON)
        results: dict[str, tuple[str, str]] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                with container.start_scope("parent") as parent:
                    session = container.resolve(Session)
                    with parent.start_scope("child"):
                        service = container.resolve(Service)
                        results[worker_id] = (session.id, service.session.id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All workers should have unique sessions
        parent_ids = [r[0] for r in results.values()]
        assert len(parent_ids) == len(set(parent_ids))

    def test_scope_disposal_during_resolution(self, container: Container) -> None:
        """Dispose while resolving: potential race condition (may pass or fail)."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)
        resolved: list[Session] = []
        errors: list[Exception] = []

        def resolver() -> None:
            try:
                for _ in range(100):
                    with container.start_scope("test"):
                        resolved.append(container.resolve(Session))
            except Exception as e:
                errors.append(e)

        def disposer() -> None:
            try:
                for _ in range(100):
                    # Try to clear any existing scopes
                    for key in list(container._scoped_instances.keys()):
                        scope_segments, _ = key
                        if scope_segments and scope_segments[0][0] == "test":
                            container.clear_scope(ScopeId(segments=scope_segments))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=resolver)
        t2 = threading.Thread(target=disposer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # If errors occurred, the race condition was exposed
        if errors:
            raise errors[0]

    def test_concurrent_async_scope_creation_same_name(self, container: Container) -> None:
        """Async tasks, same scope name: unique scope IDs."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        scope_ids: dict[str, str] = {}

        async def async_worker(worker_id: str) -> None:
            with container.start_scope("request"):
                scope_id = _current_scope.get()
                scope_ids[worker_id] = scope_id  # type: ignore[assignment]
                await asyncio.sleep(0.01)

        async def run_workers() -> None:
            await asyncio.gather(*[async_worker(f"task-{i}") for i in range(5)])

        asyncio.run(run_workers())

        # Each async task should have unique scope ID
        ids = list(scope_ids.values())
        assert len(ids) == len(set(ids))


# ============================================================================
# Scope Resolution Edge Cases
# ============================================================================


class TestScopeResolutionEdgeCases:
    """Tests for scope resolution edge cases."""

    def test_scoped_singleton_registered_globally(self, container: Container) -> None:
        """SCOPED_SINGLETON in global registry works in scope."""
        service_key = ServiceKey.from_value(Session)
        container._registry[service_key] = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED_SINGLETON,
            scope="request",
        )
        # Set flag since we're bypassing register() which normally sets this
        container._has_scoped_registrations = True

        with container.start_scope("request"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)
            assert session1 is session2

    def test_empty_factory_registration_auto_instantiates(self, container: Container) -> None:
        """factory=None, no instance: falls back to auto-instantiation."""
        service_key = ServiceKey.from_value(Session)
        container._registry[service_key] = Registration(
            service_key=service_key,
            factory=None,
            instance=None,
            lifetime=Lifetime.SCOPED_SINGLETON,
            scope="test",
        )
        # Set flag since we're bypassing register() which normally sets this
        container._has_scoped_registrations = True

        with container.start_scope("test"):
            # Container falls back to auto-instantiation when no factory/instance
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_very_deep_nested_scope_hierarchy(self, container: Container) -> None:
        """10+ levels of nesting works correctly."""
        container.register(Session, scope="level10", lifetime=Lifetime.SCOPED_SINGLETON)

        # Create 10 levels of nested scopes
        current_scope = container.start_scope("level1")
        scopes = [current_scope]
        current_scope.__enter__()

        for i in range(2, 11):
            next_scope = current_scope.start_scope(f"level{i}")
            next_scope.__enter__()
            scopes.append(next_scope)
            current_scope = next_scope

        # Should be able to resolve in deepest level
        session = container.resolve(Session)
        assert isinstance(session, Session)

        # Verify scope structure
        scope_id = _current_scope.get()
        assert scope_id is not None
        for i in range(1, 11):
            assert scope_id.contains_scope(f"level{i}")

        # Clean up
        for scope in reversed(scopes):
            scope.__exit__(None, None, None)

    def test_scope_segment_partial_match_rejected(self) -> None:
        """Scope 'req' vs registered 'request': no match."""
        container = Container(register_if_missing=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        # "req" should not match "request"
        with pytest.raises((DIWireScopeMismatchError, DIWireServiceNotRegisteredError)):  # type: ignore[call-overload]
            with container.start_scope("req"):
                container.resolve(Session)

    def test_resolve_service_nonexistent_scope(self) -> None:
        """Service for scope X, in scope Y raises DIWireServiceNotRegisteredError."""
        container = Container(register_if_missing=False)
        container.register(Session, scope="scope_x", lifetime=Lifetime.SCOPED_SINGLETON)

        with pytest.raises(DIWireServiceNotRegisteredError):
            with container.start_scope("scope_y"):
                container.resolve(Session)


# ============================================================================
# Comprehensive Captive Dependency Tests
# ============================================================================


class TestComprehensiveCaptiveDependency:
    """Comprehensive tests for captive dependency scenarios."""

    def test_singleton_capturing_scoped_persists(self, container: Container) -> None:
        """Singleton holds scoped forever: captive persists across scopes."""

        @dataclass
        class SingletonHolder:
            session: Session

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(SingletonHolder, lifetime=Lifetime.SINGLETON)

        # First scope captures the session
        with container.start_scope("request"):
            holder1 = container.resolve(SingletonHolder)
            captured_id = holder1.session.id

        # Second scope - singleton still holds first session
        with container.start_scope("request"):
            holder2 = container.resolve(SingletonHolder)
            # Captive dependency persists
            assert holder2.session.id == captured_id
            assert holder1 is holder2

    def test_transient_creating_scoped_same_scope(self, container: Container) -> None:
        """Multiple transients in scope share scoped dep."""

        @dataclass
        class TransientHolder:
            session: Session

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(TransientHolder, lifetime=Lifetime.TRANSIENT)

        with container.start_scope("request"):
            t1 = container.resolve(TransientHolder)
            t2 = container.resolve(TransientHolder)
            t3 = container.resolve(TransientHolder)

            # All transients share same scoped session
            assert t1.session is t2.session is t3.session
            # But transients themselves are different
            assert t1 is not t2 is not t3

    def test_scoped_to_scoped_different_scopes_captive(self, container: Container) -> None:
        """Scoped(A) depends on Scoped(B) in different scopes: documents captive."""
        container.register(OuterScopedService, scope="outer", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(InnerScopedService, scope="inner", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("outer") as outer:
            with outer.start_scope("inner"):
                outer_scoped = container.resolve(OuterScopedService)
                inner_id = outer_scoped.inner.id

            # Inner scope exited, but outer still holds reference
            # This documents captive behavior
            assert outer_scoped.inner.id == inner_id

    def test_mixed_lifetime_chain_crossing_boundary(self, container: Container) -> None:
        """Singleton->Transient->Scoped: works and documents behavior."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)
        container.register(TransientMiddle, lifetime=Lifetime.TRANSIENT)
        container.register(SingletonTop, lifetime=Lifetime.SINGLETON)

        with container.start_scope("request"):
            singleton = container.resolve(SingletonTop)
            captured_session_id = singleton.transient.session.id

        # Singleton captured transient which captured scoped
        with container.start_scope("request"):
            singleton2 = container.resolve(SingletonTop)
            assert singleton2.transient.session.id == captured_session_id


# ============================================================================
# Memory and Reference Edge Cases
# ============================================================================


class TestAsyncScopeContextManager:
    """Tests for async scope context manager behavior."""

    async def test_aclear_scope_called_on_async_exit(self, container: Container) -> None:
        """aclear_scope is called when async scope exits."""
        cleanup_events: list[str] = []

        async def session_factory() -> Generator[Session, None, None]:
            raise AssertionError("Should not be called - use async generator below")

        async def async_session_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="async-session")
            finally:
                cleanup_events.append("aclear_scope")

        container.register(
            Session,
            factory=async_session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        async with container.start_scope("test"):
            session = await container.aresolve(Session)
            assert session.id == "async-session"
            assert cleanup_events == []

        assert cleanup_events == ["aclear_scope"]

    async def test_async_cleanup_on_exception(self, container: Container) -> None:
        """Async scope cleanup happens even on exception."""
        cleanup_events: list[str] = []

        async def resource_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="resource")
            finally:
                cleanup_events.append("cleaned")

        container.register(
            Session,
            factory=resource_factory,
            scope="test",
            lifetime=Lifetime.SCOPED_SINGLETON,
        )

        with pytest.raises(ValueError, match="test error"):
            async with container.start_scope("test"):
                await container.aresolve(Session)
                raise ValueError("test error")

        assert cleanup_events == ["cleaned"]

    async def test_scoped_container_aresolve_works(self, container: Container) -> None:
        """ScopedContainer.aresolve() delegates correctly."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        async with container.start_scope("test") as scoped:
            session = await scoped.aresolve(Session)
            assert isinstance(session, Session)

    async def test_stale_scoped_container_aresolve_raises(
        self,
        container: Container,
    ) -> None:
        """ScopedContainer.aresolve() after exit raises error."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        async with container.start_scope("test") as scoped:
            pass

        with pytest.raises(DIWireScopeMismatchError):
            await scoped.aresolve(Session)


class TestMemoryAndReferenceEdgeCases:
    """Tests for memory and reference edge cases."""

    def test_many_scopes_created_disposed_no_leak(self, container: Container) -> None:
        """1000 scopes created/disposed: _scoped_instances empty."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED_SINGLETON)

        for _ in range(1000):
            with container.start_scope("request"):
                container.resolve(Session)

        # All scopes should be cleaned up
        assert len(container._scoped_instances) == 0

    def test_scope_disposal_releases_cached_instances(self, container: Container) -> None:
        """Scoped instances are removed from cache after scope exit."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        def has_test_scope(
            key: tuple[tuple[tuple[str | None, int], ...], object],
        ) -> bool:
            scope_segments, _ = key
            return any(name == "test" for name, _ in scope_segments)

        with container.start_scope("test"):
            container.resolve(Session)
            # Verify the instance is cached while scope is active
            test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
            assert len(test_scopes) == 1

        # After scope exit, the cache should be cleared
        test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
        assert len(test_scopes) == 0

    def test_no_reference_retention_after_clear(self, container: Container) -> None:
        """After clear_scope: no refs in container for that scope."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        with container.start_scope("test"):
            container.resolve(Session)
            # Instance should be in cache during scope
            assert len(container._scoped_instances) == 1

        # After scope exit, the scope should be cleared
        assert len(container._scoped_instances) == 0

    def test_large_scoped_instance_cleanup(self, container: Container) -> None:
        """Large objects in scope: cache is properly cleaned up on scope exit."""

        @dataclass
        class LargeObject:
            data: bytes = field(default_factory=lambda: b"x" * 10_000_000)  # 10MB
            id: str = field(default_factory=lambda: str(uuid.uuid4()))

        container.register(LargeObject, scope="test", lifetime=Lifetime.SCOPED_SINGLETON)

        def has_test_scope(
            key: tuple[tuple[tuple[str | None, int], ...], object],
        ) -> bool:
            scope_segments, _ = key
            return any(name == "test" for name, _ in scope_segments)

        for _ in range(5):
            with container.start_scope("test"):
                container.resolve(LargeObject)
                # Verify instance is cached during scope
                test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
                assert len(test_scopes) == 1

            # Verify cache is cleaned after each scope exit
            test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
            assert len(test_scopes) == 0
