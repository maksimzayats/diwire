"""Tests for scoped dependency injection."""

import asyncio
import threading
import uuid
from collections.abc import AsyncGenerator, Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Annotated, Any

import pytest

from diwire.container import Container
from diwire.container_injection import _InjectedFunction, _ScopedInjectedFunction
from diwire.container_scopes import ScopedContainer, _current_scope, _ScopeId
from diwire.exceptions import (
    DIWireAsyncCleanupWithoutEventLoopError,
    DIWireGeneratorFactoryWithoutScopeError,
    DIWireMissingDependenciesError,
    DIWireScopedWithoutScopeError,
    DIWireScopeMismatchError,
    DIWireServiceNotRegisteredError,
)
from diwire.registry import Registration
from diwire.service_key import ServiceKey
from diwire.types import Injected, Lifetime


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


class TestLifetimeScoped:
    """Tests for Lifetime.SCOPED behavior."""

    def test_scoped_value(self) -> None:
        """SCOPED has correct value."""
        assert Lifetime.SCOPED.value == "scoped"

    def test_scoped_without_scope_raises_error(self, container: Container) -> None:
        """SCOPED without scope raises error at registration time."""
        with pytest.raises(DIWireScopedWithoutScopeError):
            container.register(Session, lifetime=Lifetime.SCOPED)

    def test_scoped_within_scope_shares_instance(self, container: Container) -> None:
        """SCOPED within scope shares the same instance."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)

        assert session1.id == session2.id

    def test_scoped_different_scopes_different_instances(
        self,
        container: Container,
    ) -> None:
        """Different scopes get different SCOPED instances."""
        container.register(Session, scope="scope1", lifetime=Lifetime.SCOPED)
        container.register(Session, scope="scope2", lifetime=Lifetime.SCOPED)

        with container.enter_scope("scope1"):
            session1 = container.resolve(Session)

        with container.enter_scope("scope2"):
            session2 = container.resolve(Session)

        assert session1.id != session2.id


class TestStartScope:
    """Tests for container.enter_scope()."""

    def test_enter_scope_sets_current_scope(self, container: Container) -> None:
        """enter_scope sets the current scope context variable."""
        assert _current_scope.get() is None

        with container.enter_scope("test_scope"):
            scope = _current_scope.get()
            assert scope is not None
            assert scope.contains_scope("test_scope")

        assert _current_scope.get() is None

    def test_enter_scope_with_auto_generated_name(self, container: Container) -> None:
        """enter_scope generates unique ID if no name provided."""
        with container.enter_scope() as scoped:
            scope_id = _current_scope.get()
            assert scope_id is not None
            # Should have segments with None name and integer ID
            assert len(scope_id.segments) == 1
            name, instance_id = scope_id.segments[0]
            assert name is None
            assert isinstance(instance_id, int)

    def test_enter_scope_cleans_up_scoped_instances(self, container: Container) -> None:
        """Scoped instances are cleaned up when scope exits."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test"):
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
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test") as scoped:
            session = scoped.resolve(Session)
            assert isinstance(session, Session)

    def test_scoped_container_nested_scopes(self, container: Container) -> None:
        """Nested scopes create hierarchical scope IDs."""
        with container.enter_scope("parent") as parent:
            parent_scope = _current_scope.get()
            assert parent_scope is not None
            assert parent_scope.contains_scope("parent")

            with parent.enter_scope("child") as child:
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
        with container.enter_scope("a") as a, a.enter_scope("b") as b:
            with b.enter_scope("c") as c:
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

        def handler(service: Annotated[Service, Injected()]) -> Service:
            return service

        result = container.resolve(handler, scope="request")
        assert isinstance(result, _ScopedInjectedFunction)

    def test_scoped_injected_shares_instance_within_call(self, container: Container) -> None:
        """ScopedInjected shares scoped instances within a single call."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        def handler(
            service_a: Annotated[ServiceA, Injected()],
            service_b: Annotated[ServiceB, Injected()],
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

        def my_handler(service: Annotated[Service, Injected()]) -> None:
            pass

        result = container.resolve(my_handler, scope="request")
        assert result.__name__ == "my_handler"

    def test_scoped_injected_repr(self, container: Container) -> None:
        """ScopedInjected has informative repr."""

        def handler(service: Annotated[Service, Injected()]) -> None:
            pass

        result = container.resolve(handler, scope="request")
        assert "ScopedInjected" in repr(result)
        assert "request" in repr(result)

    def test_scoped_injected_allows_explicit_kwargs(self, container: Container) -> None:
        """ScopedInjected allows explicit kwargs to override injected ones."""

        def handler(value: int, service: Annotated[Service, Injected()]) -> tuple[int, Service]:
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
        container = Container(autoregister=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with pytest.raises(DIWireServiceNotRegisteredError), container.enter_scope("other_scope"):
            container.resolve(Session)

    def test_scoped_service_not_found_without_scope(self) -> None:
        """Resolving scoped service with no active scope raises DIWireServiceNotRegisteredError."""
        container = Container(autoregister=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with pytest.raises(DIWireServiceNotRegisteredError):
            container.resolve(Session)

    def test_scope_mismatch_error_with_global_registration(self) -> None:
        """DIWireScopeMismatchError raised when global registration has scope that doesn't match."""
        # This tests the case where registration is in global registry with scope set
        container = Container(autoregister=False)
        service_key = ServiceKey.from_value(Session)
        container._registry[service_key] = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )
        # Set flag since we're bypassing register() which normally sets this
        container._has_scoped_registrations = True

        with pytest.raises(DIWireScopeMismatchError) as exc_info, container.enter_scope("wrong"):
            container.resolve(Session)

        error = exc_info.value
        assert error.registered_scope == "request"
        assert error.current_scope is not None
        assert error.current_scope.startswith("wrong/")

    def test_autoregister_raises_error_when_scoped_registration_exists(self) -> None:
        """Auto-registration raises DIWireScopeMismatchError when a scoped registration exists."""
        container = Container(autoregister=True)
        container.register(Session, scope="app", lifetime=Lifetime.SCOPED)

        with pytest.raises(DIWireScopeMismatchError) as exc_info:
            container.resolve(Session)

        error = exc_info.value
        assert error.registered_scope == "app"
        assert error.current_scope is None

    def test_autoregister_raises_error_in_wrong_scope(self) -> None:
        """Auto-registration raises DIWireScopeMismatchError when resolved in wrong scope."""
        container = Container(autoregister=True)
        container.register(Session, scope="app", lifetime=Lifetime.SCOPED)

        with pytest.raises(DIWireScopeMismatchError) as exc_info, container.enter_scope("other"):
            container.resolve(Session)

        error = exc_info.value
        assert error.registered_scope == "app"
        assert error.current_scope is not None

    def test_autoregister_still_works_for_unregistered_types(self) -> None:
        """Types with no scoped registration are still auto-registered normally."""

        @dataclass
        class Unrelated:
            pass

        container = Container(autoregister=True)
        container.register(Session, scope="app", lifetime=Lifetime.SCOPED)

        # Unrelated has no scoped registration, so auto-registration should work
        result = container.resolve(Unrelated)
        assert isinstance(result, Unrelated)

    def test_matching_scope_succeeds(self, container: Container) -> None:
        """Resolving in matching scope succeeds."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request"):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_child_scope_can_access_parent_scope_registration(self, container: Container) -> None:
        """Child scopes can resolve services registered for parent scope."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request") as parent, parent.enter_scope("child"):
            # Current scope is "request/child" which starts with "request"
            session = container.resolve(Session)
            assert isinstance(session, Session)


class TestScopedRegistration:
    """Tests for per-scope registration."""

    def test_multiple_scoped_registrations(self, container: Container) -> None:
        """Same service can have different registrations for different scopes."""
        container.register(Session, scope="scope_a", lifetime=Lifetime.SCOPED)
        container.register(Session, scope="scope_b", lifetime=Lifetime.SCOPED)

        with container.enter_scope("scope_a"):
            session_a = container.resolve(Session)

        with container.enter_scope("scope_b"):
            session_b = container.resolve(Session)

        # Different scopes, different instances
        assert session_a.id != session_b.id

    def test_scoped_registration_independent_of_global(self, container: Container) -> None:
        """Scoped and global registrations work independently."""
        # Scoped registration only
        container.register(Session, scope="special", lifetime=Lifetime.SCOPED)

        # Inside special scope - uses scoped registration
        with container.enter_scope("special"):
            session1 = container.resolve(Session)
            session2 = container.resolve(Session)
            # Same instance within scope
            assert session1.id == session2.id

        # Different scope instance
        with container.enter_scope("special"):
            session3 = container.resolve(Session)
            assert session3.id != session1.id

    def test_most_specific_scope_wins(self, container: Container) -> None:
        """Most specific matching scope registration is used."""
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED)
        container.register(Session, scope="child", lifetime=Lifetime.SCOPED)

        with container.enter_scope("parent") as parent:
            session_parent = container.resolve(Session)

            with parent.enter_scope("child"):
                # "child" is more specific than "parent"
                session_child = container.resolve(Session)

        # Different registrations, different instances
        assert session_parent.id != session_child.id


class TestScopedInstanceCaching:
    """Tests for scoped instance caching behavior."""

    def test_scoped_instances_cached_at_registration_scope(self, container: Container) -> None:
        """Scoped instances are cached at the registration's scope level."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request") as parent:
            session_parent = container.resolve(Session)

            with parent.enter_scope("child"):
                # Should get same instance because cached at "request" level
                session_child = container.resolve(Session)

            # Back in parent scope, same instance
            session_parent2 = container.resolve(Session)

        assert session_parent.id == session_child.id == session_parent2.id

    def test_scoped_instances_isolated_between_scopes(self, container: Container) -> None:
        """Different scope instances don't share scoped singletons."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        sessions = []
        for i in range(3):
            with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
            scope="request",
        )

        def handler(
            service_a: Annotated[ServiceA, Injected()],
            service_b: Annotated[ServiceB, Injected()],
        ) -> tuple[ServiceA, ServiceB]:
            return service_a, service_b

        # No explicit scope - should auto-detect from Session dependency
        request_handler = container.resolve(handler)

        # Should be _ScopedInjectedFunction because Session has scope="request"
        assert isinstance(request_handler, _ScopedInjectedFunction)

    def test_explicit_scope_overrides_auto_detection(self, container: Container) -> None:
        """Explicit scope parameter overrides auto-detection."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        def handler(service: Annotated[Service, Injected()]) -> Service:
            return service

        # Explicit scope
        result = container.resolve(handler, scope="custom")
        assert isinstance(result, _ScopedInjectedFunction)

    def test_no_scope_returns_injected(self, container: Container) -> None:
        """Without scoped dependencies, resolve returns regular Injected."""
        container.register(Session, lifetime=Lifetime.TRANSIENT)

        def handler(service: Annotated[Service, Injected()]) -> Service:
            return service

        result = container.resolve(handler)
        assert isinstance(result, _InjectedFunction)
        assert not isinstance(result, _ScopedInjectedFunction)

    def test_auto_detect_scope_from_scoped_registry(self, container: Container) -> None:
        """resolve() auto-detects scope from scoped_registry."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        def handler(session: Annotated[Session, Injected()]) -> Session:
            return session

        injected = container.resolve(handler)
        assert isinstance(injected, _ScopedInjectedFunction)

    def test_ambiguous_scope_detection_returns_none(self, container: Container) -> None:
        """Ambiguous scopes (different values) don't auto-detect."""
        # Register same service in multiple scopes
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container._scoped_registry[(ServiceKey.from_value(Session), "session")] = Registration(
            service_key=ServiceKey.from_value(Session),
            lifetime=Lifetime.SCOPED,
            scope="session",
        )

        def handler(session: Annotated[Session, Injected()]) -> Session:
            return session

        injected = container.resolve(handler)
        # Should not auto-detect scope due to ambiguity
        assert isinstance(injected, _InjectedFunction)
        assert not isinstance(injected, _ScopedInjectedFunction)


class TestScopeHierarchyMatching:
    """Tests for scope hierarchy matching logic."""

    def test_exact_scope_match(self, container: Container) -> None:
        """Exact scope name matches."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request"):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_parent_scope_matches_child(self, container: Container) -> None:
        """Parent scope registration matches in child scopes."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request") as parent, parent.enter_scope("handler"):
            # "request/handler" contains "request" as parent
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_segment_scope_matches(self, container: Container) -> None:
        """Scope registered as segment matches in hierarchy."""
        container.register(Session, scope="handler", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request") as request, request.enter_scope("handler"):
            # "request/handler" contains "handler" as segment
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_non_matching_scope_not_found(self) -> None:
        """Non-matching scope raises DIWireServiceNotRegisteredError."""
        container = Container(autoregister=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with pytest.raises(DIWireServiceNotRegisteredError), container.enter_scope("other"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(Session, scope="default", lifetime=Lifetime.SCOPED)

        # In "special" scope - should return the registered instance
        with container.enter_scope("special"):
            session = container.resolve(Session)
            assert session.id == "specific-1234"

        # In "default" scope - should create a new instance (not the specific one)
        with container.enter_scope("default"):
            session = container.resolve(Session)
            assert session.id != "specific-1234"

    def test_scoped_instance_not_cached_in_global_singletons(self, container: Container) -> None:
        """Scoped instance should be cached in _scoped_instances, not _singletons."""
        specific_session = Session(id="scoped-instance")
        container.register(
            Session,
            instance=specific_session,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        service_key = ServiceKey.from_value(Session)

        with container.enter_scope("test"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Session,
            instance=session_b,
            scope="scope_b",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("scope_a"):
            resolved_a = container.resolve(Session)
            assert resolved_a.id == "scope-a-session"

        with container.enter_scope("scope_b"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Session,
            instance=inner_session,
            scope="inner",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("outer") as outer:
            # In outer scope - should return outer instance
            assert container.resolve(Session).id == "outer-session"

            with outer.enter_scope("inner"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Session,
            instance=admin_session,
            scope="admin",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("request"):
            service_a = container.resolve(ServiceA)
            service_b = container.resolve(ServiceB)
            assert service_a.session.id == "request-session"
            assert service_b.session.id == "request-session"

        with container.enter_scope("admin"):
            service_a = container.resolve(ServiceA)
            service_b = container.resolve(ServiceB)
            assert service_a.session.id == "admin-session"
            assert service_b.session.id == "admin-session"


class TestScopeCleanup:
    """Tests for scope cleanup behavior."""

    def test_nested_scope_cleanup(self, container: Container) -> None:
        """Nested scopes clean up their instances independently."""
        container.register(Session, scope="child", lifetime=Lifetime.SCOPED)

        with container.enter_scope("parent") as parent:
            with parent.enter_scope("child"):
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
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        try:
            with container.enter_scope("test"):
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

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container.register(SingletonService, lifetime=Lifetime.SINGLETON)

        # First request scope
        with container.enter_scope("request"):
            singleton1 = container.resolve(SingletonService)
            captured_session_id = singleton1.session.id

        # Second request scope - the singleton still has the old session!
        with container.enter_scope("request"):
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

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container.register(TransientService, lifetime=Lifetime.TRANSIENT)

        with container.enter_scope("request"):
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
        container.register(Session, scope="my/scope", lifetime=Lifetime.SCOPED)

        # This might break the hierarchy parsing since "/" is used as separator
        with container.enter_scope("my/scope"):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_empty_scope_name(self, container: Container) -> None:
        """Empty string as scope name."""
        container.register(Session, scope="", lifetime=Lifetime.SCOPED)

        with container.enter_scope(""):
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_reenter_same_scope_name(self, container: Container) -> None:
        """Re-entering a scope with the same name creates fresh instances."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request"):
            session1 = container.resolve(Session)

        # Re-enter with same name - should be a fresh scope
        with container.enter_scope("request"):
            session2 = container.resolve(Session)

        assert session1.id != session2.id

    def test_resolve_container_within_scope(self, container: Container) -> None:
        """Resolving Container within different scopes returns same instance."""
        with container.enter_scope("scope1"):
            c1 = container.resolve(Container)

        with container.enter_scope("scope2"):
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
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Session,
            instance=Session(id="second"),
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("test"):
            session = container.resolve(Session)
            assert session.id == "second"

    def test_resolve_after_scope_exits_via_stale_scoped_container(
        self,
        container: Container,
    ) -> None:
        """Resolving via stale ScopedContainer after scope exits."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test") as scoped:
            session_inside = scoped.resolve(Session)

        # The scope has exited, but we still have reference to scoped container
        # This resolves using the container but scope context is gone
        with pytest.raises((DIWireScopeMismatchError, DIWireServiceNotRegisteredError)):  # type: ignore[no-matching-overload]
            scoped.resolve(Session)

    def test_concurrent_scope_same_name_different_instances(self, container: Container) -> None:
        """Concurrent scopes with same name should be isolated."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        results: dict[str, str] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )

        # Outside scope - should get global
        session_outside = container.resolve(Session)
        assert session_outside.id == "global"

        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )

        # Outside special scope - uses global transient
        s1 = container.resolve(Session)
        s2 = container.resolve(Session)
        assert s1 is not s2  # Transient creates new instances

        # Inside special scope - uses scoped instance
        with container.enter_scope("special"):
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

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request"):
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

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container.register(TransientDep, lifetime=Lifetime.TRANSIENT)
        container.register(SingletonDep, lifetime=Lifetime.SINGLETON)

        with container.enter_scope("request"):
            singleton1 = container.resolve(SingletonDep)
            captured_session_id = singleton1.transient.session.id

        with container.enter_scope("request"):
            singleton2 = container.resolve(SingletonDep)
            # Singleton captured the transient which captured the scoped session
            assert singleton2.transient.session.id == captured_session_id


class TestScopeContextVariableIsolation:
    """Tests for context variable isolation across threads/async."""

    def test_scope_context_isolated_between_threads(self, container: Container) -> None:
        """Each thread should have its own scope context."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        scope_values: dict[str, Any] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                # Check scope is None initially
                scope_values[f"{worker_id}_before"] = _current_scope.get()

                with container.enter_scope(f"scope-{worker_id}"):
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
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        results: dict[str, str] = {}

        async def async_worker(worker_id: str) -> None:
            with container.enter_scope("request"):
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
        container.register(ScopedLevel1, scope="request", lifetime=Lifetime.SCOPED)
        container.register(ScopedLevel2, scope="request", lifetime=Lifetime.SCOPED)
        container.register(ScopedLevel3, scope="request", lifetime=Lifetime.SCOPED)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request"):
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
        container.register(ScopedLevel2, scope="outer", lifetime=Lifetime.SCOPED)
        container.register(ScopedLevel3, scope="inner", lifetime=Lifetime.SCOPED)
        container.register(Session, scope="inner", lifetime=Lifetime.SCOPED)

        with container.enter_scope("outer") as outer:
            with outer.enter_scope("inner"):
                level2 = container.resolve(ScopedLevel2)
                assert isinstance(level2, ScopedLevel2)
                assert isinstance(level2.level3.session, Session)

    def test_long_transitive_chain_all_scoped(self, container: Container) -> None:
        """5+ scoped services in chain: bottom service is shared."""
        container.register(ChainA, scope="request", lifetime=Lifetime.SCOPED)
        container.register(ChainB, scope="request", lifetime=Lifetime.SCOPED)
        container.register(ChainC, scope="request", lifetime=Lifetime.SCOPED)
        container.register(ChainD, scope="request", lifetime=Lifetime.SCOPED)
        container.register(ChainE, scope="request", lifetime=Lifetime.SCOPED)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        with container.enter_scope("request"):
            chain_a = container.resolve(ChainA)
            session_direct = container.resolve(Session)

            # Bottom service Session should be shared
            assert chain_a.b.c.d.e.session is session_direct

    def test_transitive_scoped_resolved_outside_scope(self) -> None:
        """A -> B(scoped:special) resolved outside scope raises error."""
        container = Container(autoregister=False)

        container.register(OuterService, lifetime=Lifetime.TRANSIENT)
        container.register(InnerService, scope="special", lifetime=Lifetime.SCOPED)

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
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Session,
            factory=FailingChildFactory,
            scope="child",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("parent") as parent:
            # Parent scope works
            session_in_parent = container.resolve(Session)
            assert session_in_parent.id == "parent-session"

            try:
                with parent.enter_scope("child"):
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
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )

        sessions = []
        for _ in range(3):
            with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Session,
            factory=child_factory,
            scope="child",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("parent") as parent:
            parent_session = container.resolve(Session)
            assert parent_session.id == "parent"
            assert cleanup_events == []

            with parent.enter_scope("child"):
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
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED)

        with container.enter_scope("parent") as parent:
            parent_session = container.resolve(Session)

            try:
                with parent.enter_scope("child"):
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
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        try:
            with container.enter_scope("test"):
                container.resolve(Session)
                raise RuntimeError("Error during scope")
        except RuntimeError:
            pass

        assert _current_scope.get() is None

    def test_resolve_from_manually_cleared_scope(self, container: Container) -> None:
        """Manual clear_scope then resolve: creates new instance (cache cleared)."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test") as scoped:
            session1 = container.resolve(Session)
            scope_id = _current_scope.get()

            # Manually clear the scope (unusual operation)
            container._clear_scope(scope_id)  # type: ignore[arg-type]

            # After clearing, a new instance is created (cache was emptied)
            session2 = container.resolve(Session)
            assert session1.id != session2.id

    def test_double_exit_scope_idempotent(self, container: Container) -> None:
        """__exit__ called twice: clear_scope on already-cleared scope is safe."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        # Use the context manager normally
        with container.enter_scope("test") as scoped:
            container.resolve(Session)
            scope_id = scoped._scope_id

        # The scope should be cleared after normal exit
        # Check that no keys have matching scope segments
        assert not any(k[0] == scope_id.segments for k in container._scoped_instances)

        # Manually calling clear_scope again should be idempotent (no error)
        container._clear_scope(scope_id)

        # Still no error and scope context is None
        assert _current_scope.get() is None

    def test_close_sync_continues_when_reset_fails(self, container: Container) -> None:
        """_close_sync completes cleanup even if ContextVar reset fails."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test") as scoped:
            container.resolve(Session)
            # Manually reset the token to simulate different context
            # This makes the token invalid for reset in _close_sync
            _current_scope.reset(scoped._token)

        # Despite reset failure, cleanup should complete
        assert len(container._scoped_instances) == 0
        assert scoped._exited is True
        assert scoped not in container._active_scopes

    async def test_close_async_continues_when_reset_fails(self, container: Container) -> None:
        """_close_async completes cleanup even if ContextVar reset fails."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        async with container.enter_scope("test") as scoped:
            await container.aresolve(Session)
            # Manually reset the token to simulate different context
            _current_scope.reset(scoped._token)

        # Despite reset failure, cleanup should complete
        assert len(container._scoped_instances) == 0
        assert scoped._exited is True
        assert scoped not in container._active_scopes


# ============================================================================
# Concurrent Scope Edge Cases
# ============================================================================


class TestConcurrentScopeEdgeCases:
    """Tests for concurrent scope edge cases."""

    def test_same_scope_name_concurrent_threads_isolated(self, container: Container) -> None:
        """Multiple threads, same scope name: complete isolation."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        results: dict[str, str] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                with container.enter_scope("request"):
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
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED)
        container.register(Service, scope="child", lifetime=Lifetime.SCOPED)
        results: dict[str, tuple[str, str]] = {}
        errors: list[Exception] = []

        def worker(worker_id: str) -> None:
            try:
                with container.enter_scope("parent") as parent:
                    session = container.resolve(Session)
                    with parent.enter_scope("child"):
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

    def test_scope_disposal_during_resolution_is_robust(  # noqa: C901
        self,
        container: Container,
    ) -> None:
        """Concurrent scope disposal during resolution must not crash or corrupt state.

        Expected race condition errors (KeyError, RuntimeError) are acceptable.
        The test verifies the container remains functional after concurrent stress.
        """
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)
        resolved: list[Session] = []
        unexpected_errors: list[Exception] = []
        expected_race_errors = (KeyError, RuntimeError)

        def resolver() -> None:
            for _ in range(100):
                try:
                    with container.enter_scope("test"):
                        resolved.append(container.resolve(Session))
                except expected_race_errors:  # noqa: PERF203
                    pass  # Expected race condition outcome
                except Exception as e:
                    unexpected_errors.append(e)

        def disposer() -> None:
            for _ in range(100):
                try:
                    for key in list(container._scoped_instances.keys()):
                        scope_segments, _ = key
                        if scope_segments and scope_segments[0][0] == "test":
                            container._clear_scope(_ScopeId(segments=scope_segments))
                except expected_race_errors:  # noqa: PERF203
                    pass  # Expected race condition outcome
                except Exception as e:
                    unexpected_errors.append(e)

        t1 = threading.Thread(target=resolver)
        t2 = threading.Thread(target=disposer)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Verify no deadlock
        assert not t1.is_alive(), "Resolver thread hung"
        assert not t2.is_alive(), "Disposer thread hung"

        # Only unexpected errors should fail
        assert not unexpected_errors, f"Unexpected errors: {unexpected_errors}"

        # Verify container still functional
        with container.enter_scope("test"):
            post_stress = container.resolve(Session)
            assert isinstance(post_stress, Session)

    def test_concurrent_async_scope_creation_same_name(self, container: Container) -> None:
        """Async tasks, same scope name: unique scope IDs."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        scope_ids: dict[str, str] = {}

        async def async_worker(worker_id: str) -> None:
            with container.enter_scope("request"):
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

    def test_scoped_registered_globally(self, container: Container) -> None:
        """SCOPED in global registry works in scope."""
        service_key = ServiceKey.from_value(Session)
        container._registry[service_key] = Registration(
            service_key=service_key,
            lifetime=Lifetime.SCOPED,
            scope="request",
        )
        # Set flag since we're bypassing register() which normally sets this
        container._has_scoped_registrations = True

        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
            scope="test",
        )
        # Set flag since we're bypassing register() which normally sets this
        container._has_scoped_registrations = True

        with container.enter_scope("test"):
            # Container falls back to auto-instantiation when no factory/instance
            session = container.resolve(Session)
            assert isinstance(session, Session)

    def test_very_deep_nested_scope_hierarchy(self, container: Container) -> None:
        """10+ levels of nesting works correctly."""
        container.register(Session, scope="level10", lifetime=Lifetime.SCOPED)

        # Create 10 levels of nested scopes
        current_scope = container.enter_scope("level1")
        scopes = [current_scope]
        current_scope.__enter__()

        for i in range(2, 11):
            next_scope = current_scope.enter_scope(f"level{i}")
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
        container = Container(autoregister=False)
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        # "req" should not match "request"
        with pytest.raises((DIWireScopeMismatchError, DIWireServiceNotRegisteredError)):  # type: ignore[call-overload]
            with container.enter_scope("req"):
                container.resolve(Session)

    def test_resolve_service_nonexistent_scope(self) -> None:
        """Service for scope X, in scope Y raises DIWireServiceNotRegisteredError."""
        container = Container(autoregister=False)
        container.register(Session, scope="scope_x", lifetime=Lifetime.SCOPED)

        with pytest.raises(DIWireServiceNotRegisteredError):
            with container.enter_scope("scope_y"):
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

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container.register(SingletonHolder, lifetime=Lifetime.SINGLETON)

        # First scope captures the session
        with container.enter_scope("request"):
            holder1 = container.resolve(SingletonHolder)
            captured_id = holder1.session.id

        # Second scope - singleton still holds first session
        with container.enter_scope("request"):
            holder2 = container.resolve(SingletonHolder)
            # Captive dependency persists
            assert holder2.session.id == captured_id
            assert holder1 is holder2

    def test_transient_creating_scoped_same_scope(self, container: Container) -> None:
        """Multiple transients in scope share scoped dep."""

        @dataclass
        class TransientHolder:
            session: Session

        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container.register(TransientHolder, lifetime=Lifetime.TRANSIENT)

        with container.enter_scope("request"):
            t1 = container.resolve(TransientHolder)
            t2 = container.resolve(TransientHolder)
            t3 = container.resolve(TransientHolder)

            # All transients share same scoped session
            assert t1.session is t2.session is t3.session
            # But transients themselves are different
            assert t1 is not t2 is not t3

    def test_scoped_to_scoped_different_scopes_captive(self, container: Container) -> None:
        """Scoped(A) depends on Scoped(B) in different scopes: documents captive."""
        container.register(OuterScopedService, scope="outer", lifetime=Lifetime.SCOPED)
        container.register(InnerScopedService, scope="inner", lifetime=Lifetime.SCOPED)

        with container.enter_scope("outer") as outer:
            with outer.enter_scope("inner"):
                outer_scoped = container.resolve(OuterScopedService)
                inner_id = outer_scoped.inner.id

            # Inner scope exited, but outer still holds reference
            # This documents captive behavior
            assert outer_scoped.inner.id == inner_id

    def test_mixed_lifetime_chain_crossing_boundary(self, container: Container) -> None:
        """Singleton->Transient->Scoped: works and documents behavior."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)
        container.register(TransientMiddle, lifetime=Lifetime.TRANSIENT)
        container.register(SingletonTop, lifetime=Lifetime.SINGLETON)

        with container.enter_scope("request"):
            singleton = container.resolve(SingletonTop)
            captured_session_id = singleton.transient.session.id

        # Singleton captured transient which captured scoped
        with container.enter_scope("request"):
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
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("test"):
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
            lifetime=Lifetime.SCOPED,
        )

        with pytest.raises(ValueError, match="test error"):
            async with container.enter_scope("test"):
                await container.aresolve(Session)
                raise ValueError("test error")

        assert cleanup_events == ["cleaned"]

    async def test_scoped_container_aresolve_works(self, container: Container) -> None:
        """ScopedContainer.aresolve() delegates correctly."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        async with container.enter_scope("test") as scoped:
            session = await scoped.aresolve(Session)
            assert isinstance(session, Session)

    async def test_stale_scoped_container_aresolve_raises(
        self,
        container: Container,
    ) -> None:
        """ScopedContainer.aresolve() after exit raises error."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        async with container.enter_scope("test") as scoped:
            pass

        with pytest.raises(DIWireScopeMismatchError):
            await scoped.aresolve(Session)


class TestScopedSingletonConcurrency:
    """Tests for scoped singleton behavior under concurrent async resolution."""

    async def test_concurrent_scoped_singleton_aresolve_shares_instance(
        self,
        container: Container,
    ) -> None:
        """Concurrent aresolve within a scope returns the same instance."""
        call_count = 0
        factory_started = asyncio.Event()
        factory_release = asyncio.Event()

        async def session_factory() -> Session:
            nonlocal call_count
            call_count += 1
            call_id = call_count
            factory_started.set()
            await factory_release.wait()
            return Session(id=f"session-{call_id}")

        container.register(
            Session,
            factory=session_factory,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("request"):
            task1 = asyncio.create_task(container.aresolve(Session))
            await factory_started.wait()
            task2 = asyncio.create_task(container.aresolve(Session))
            await asyncio.sleep(0)
            factory_release.set()
            session1, session2 = await asyncio.gather(task1, task2)

        assert session1 is session2
        assert call_count == 1


class TestMemoryAndReferenceEdgeCases:
    """Tests for memory and reference edge cases."""

    def test_many_scopes_created_disposed_no_leak(self, container: Container) -> None:
        """1000 scopes created/disposed: _scoped_instances empty."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        for _ in range(1000):
            with container.enter_scope("request"):
                container.resolve(Session)

        # All scopes should be cleaned up
        assert len(container._scoped_instances) == 0

    def test_scope_disposal_releases_cached_instances(self, container: Container) -> None:
        """Scoped instances are removed from cache after scope exit."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        def has_test_scope(
            key: tuple[tuple[tuple[str | None, int], ...], object],
        ) -> bool:
            scope_segments, _ = key
            return any(name == "test" for name, _ in scope_segments)

        with container.enter_scope("test"):
            container.resolve(Session)
            # Verify the instance is cached while scope is active
            test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
            assert len(test_scopes) == 1

        # After scope exit, the cache should be cleared
        test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
        assert len(test_scopes) == 0

    def test_no_reference_retention_after_clear(self, container: Container) -> None:
        """After clear_scope: no refs in container for that scope."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test"):
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

        container.register(LargeObject, scope="test", lifetime=Lifetime.SCOPED)

        def has_test_scope(
            key: tuple[tuple[tuple[str | None, int], ...], object],
        ) -> bool:
            scope_segments, _ = key
            return any(name == "test" for name, _ in scope_segments)

        for _ in range(5):
            with container.enter_scope("test"):
                container.resolve(LargeObject)
                # Verify instance is cached during scope
                test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
                assert len(test_scopes) == 1

            # Verify cache is cleaned after each scope exit
            test_scopes = [k for k in container._scoped_instances if has_test_scope(k)]
            assert len(test_scopes) == 0


# ============================================================================
# Async Scoped Singleton Lock Cleanup Tests (line 807)
# ============================================================================


class TestAsyncScopedSingletonLockCleanup:
    """Tests for async scoped singleton lock cleanup on scope exit."""

    def test_async_scoped_singleton_lock_cleanup_via_sync_close_scope(
        self,
        container: Container,
    ) -> None:
        """Async scoped singleton locks are cleaned up via sync close_scope().

        This test covers line 807 in container.py where async scoped singleton
        locks are deleted during close_scope() (the sync version).
        """

        async def session_factory() -> Session:
            return Session(id="async-created")

        container.register(
            Session,
            factory=session_factory,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        # Use sync context manager to enter scope
        with container.enter_scope("request"):
            # Create async lock by running aresolve in a new event loop
            async def resolve_async() -> Session:
                return await container.aresolve(Session)

            loop = asyncio.new_event_loop()
            try:
                session = loop.run_until_complete(resolve_async())
            finally:
                loop.close()

            assert session.id == "async-created"

            # Verify async lock was created while scope is active
            assert len(container._locks._scoped_singleton_locks) > 0

        # After sync scope exit (close_scope), async locks should be cleaned up (line 807)
        assert len(container._locks._scoped_singleton_locks) == 0

    async def test_async_scoped_singleton_lock_cleanup_via_async_clear_scope(
        self,
        container: Container,
    ) -> None:
        """Async scoped singleton locks are cleaned up via aclear_scope().

        This test covers line 1932 in container.py where async scoped singleton
        locks are deleted during aclear_scope() (the async version).
        """

        async def session_factory() -> Session:
            return Session()

        container.register(
            Session,
            factory=session_factory,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("request"):
            # Resolve via aresolve to ensure async lock is created
            await container.aresolve(Session)
            assert len(container._locks._scoped_singleton_locks) > 0

        # After async scope exit, async locks should be cleaned up
        assert len(container._locks._scoped_singleton_locks) == 0


# ============================================================================
# Scoped Singleton Double-Check Locking Tests (lines 1320, 1376-1377, 1386, 1653)
# ============================================================================


class TestScopedSingletonDoubleCheckLocking:
    """Tests for scoped singleton double-check locking paths."""

    def test_scoped_singleton_with_registered_instance_sync(
        self,
        container: Container,
    ) -> None:
        """Scoped singleton with pre-registered instance releases lock correctly.

        This test covers lines 1385-1386 in container.py where the scoped lock
        is released when a registration already has an instance.
        """
        specific_session = Session(id="pre-registered")

        container.register(
            Session,
            instance=specific_session,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        with container.enter_scope("test"):
            # First resolve will acquire lock and find instance in registration
            session1 = container.resolve(Session)
            assert session1.id == "pre-registered"

            # Second resolve should also work (lock was properly released)
            session2 = container.resolve(Session)
            assert session1 is session2

    async def test_scoped_singleton_with_registered_instance_async(
        self,
        container: Container,
    ) -> None:
        """Async scoped singleton with pre-registered instance releases lock correctly.

        This test covers line 1653 in container.py where the scoped lock
        is released when a registration already has an instance in async path.
        """
        specific_session = Session(id="async-pre-registered")

        container.register(
            Session,
            instance=specific_session,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("test"):
            # First resolve via aresolve will acquire async lock and find instance
            session1 = await container.aresolve(Session)
            assert session1.id == "async-pre-registered"

            # Second resolve should also work (lock was properly released)
            session2 = await container.aresolve(Session)
            assert session1 is session2

    async def test_scoped_singleton_double_check_async_path(
        self,
        container: Container,
    ) -> None:
        """Async scoped singleton double-check locking returns cached value.

        This tests the async double-check locking path where concurrent
        coroutines compete for the same scoped singleton instance.
        """
        call_count = 0
        factory_started = asyncio.Event()
        factory_release = asyncio.Event()

        async def slow_session_factory() -> Session:
            nonlocal call_count
            call_count += 1
            call_id = call_count
            factory_started.set()  # Signal that factory has started
            await factory_release.wait()  # Wait for release signal
            return Session(id=f"session-{call_id}")

        container.register(
            Session,
            factory=slow_session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async with container.enter_scope("test"):
            # Start first resolution - this will hold the lock
            task1 = asyncio.create_task(container.aresolve(Session))

            # Wait for factory to start (meaning lock is held)
            await factory_started.wait()

            # Start second resolution - this will wait for lock then hit double-check
            task2 = asyncio.create_task(container.aresolve(Session))

            # Give task2 time to reach the lock
            await asyncio.sleep(0.01)

            # Release the factory
            factory_release.set()

            # Wait for both tasks
            session1, session2 = await asyncio.gather(task1, task2)

        # Factory should only be called once due to double-check locking
        assert call_count == 1
        # Both tasks should get the same instance
        assert session1 is session2


# ============================================================================
# Scoped Ignored Types Tests (lines 1782-1788, 2082-2088)
# ============================================================================


@dataclass
class ServiceWithStr:
    """A service that depends on str (ignored type)."""

    name: str


@dataclass
class ServiceWithStrDefault:
    """A service that depends on str with a default value."""

    name: str = "default_name"


class TestScopedIgnoredTypes:
    """Test ignored types (str, int, etc.) with scoped registrations."""

    def test_scoped_registered_str_resolves_sync(self, container: Container) -> None:
        """Sync: str registered in scope should be resolved, not marked as missing."""
        container.register(str, instance="scoped_value", scope="request")
        container.register(ServiceWithStr)

        with container.enter_scope("request"):
            service = container.resolve(ServiceWithStr)
            assert service.name == "scoped_value"

    async def test_scoped_registered_str_resolves_async(self, container: Container) -> None:
        """Async: str registered in scope should be resolved, not marked as missing."""
        container.register(str, instance="async_scoped_value", scope="request")
        container.register(ServiceWithStr)

        async with container.enter_scope("request"):
            service = await container.aresolve(ServiceWithStr)
            assert service.name == "async_scoped_value"

    def test_scoped_ignored_type_with_default_uses_scoped_value(
        self,
        container: Container,
    ) -> None:
        """Scoped registration takes precedence over default value."""
        container.register(str, instance="from_scope", scope="request")
        container.register(ServiceWithStrDefault)

        with container.enter_scope("request"):
            service = container.resolve(ServiceWithStrDefault)
            # Scoped value should be used, not the default
            assert service.name == "from_scope"

    def test_ignored_type_in_nested_scope_resolves(self, container: Container) -> None:
        """Ignored type registered in parent scope resolves in nested scope."""
        container.register(str, instance="parent_value", scope="parent")
        container.register(ServiceWithStr)

        with container.enter_scope("parent"):
            # Nested scope should still find the parent's scoped registration
            with container.enter_scope("child"):
                service = container.resolve(ServiceWithStr)
                assert service.name == "parent_value"

    def test_ignored_type_outside_scope_uses_default(self, container: Container) -> None:
        """Outside scope, ignored type with default uses default (not scoped value)."""
        container.register(str, instance="scoped_value", scope="request")
        container.register(ServiceWithStrDefault)

        # Outside the scope, the scoped registration is not visible
        # So the default value should be used
        service = container.resolve(ServiceWithStrDefault)
        assert service.name == "default_name"

    async def test_ignored_type_outside_scope_uses_default_async(
        self,
        container: Container,
    ) -> None:
        """Async: Outside scope, ignored type with default uses default (not scoped value)."""
        container.register(str, instance="scoped_value", scope="request")
        container.register(ServiceWithStrDefault)

        # Outside the scope, the scoped registration is not visible
        # So the default value should be used (async path)
        service = await container.aresolve(ServiceWithStrDefault)
        assert service.name == "default_name"

    def test_ignored_type_outside_scope_without_default_raises(
        self,
        container: Container,
    ) -> None:
        """Outside scope, ignored type without default raises error."""
        container.register(str, instance="scoped_value", scope="request")
        container.register(ServiceWithStr)

        # Outside the scope, str is not registered globally and has no default
        with pytest.raises(DIWireMissingDependenciesError):
            container.resolve(ServiceWithStr)

    async def test_ignored_type_in_nested_scope_resolves_async(
        self,
        container: Container,
    ) -> None:
        """Async: Ignored type registered in parent scope resolves in nested scope."""
        container.register(str, instance="async_parent_value", scope="parent")
        container.register(ServiceWithStr)

        async with container.enter_scope("parent"):
            async with container.enter_scope("child"):
                service = await container.aresolve(ServiceWithStr)
                assert service.name == "async_parent_value"

    def test_multiple_ignored_types_in_scope(self, container: Container) -> None:
        """Multiple ignored types can be registered and resolved in scope."""

        @dataclass
        class ServiceWithMultipleIgnored:
            name: str
            count: int
            ratio: float

        container.register(str, instance="test_name", scope="request")
        container.register(int, instance=42, scope="request")
        container.register(float, instance=3.14, scope="request")
        container.register(ServiceWithMultipleIgnored)

        with container.enter_scope("request"):
            service = container.resolve(ServiceWithMultipleIgnored)
            assert service.name == "test_name"
            assert service.count == 42
            assert service.ratio == 3.14


class TestSyncScopeAsyncCleanup:
    """Tests for async generator cleanup when using sync scope context manager."""

    async def test_clear_scope_closes_async_exit_stacks_with_running_loop(
        self,
        container: Container,
    ) -> None:
        """clear_scope() closes async exit stacks when event loop is running."""
        cleanup_events: list[str] = []

        async def async_session_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="async-session")
            finally:
                cleanup_events.append("cleaned_async")

        container.register(
            Session,
            factory=async_session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        # Use sync scope but resolve async generator with aresolve
        with container.enter_scope("test"):
            session = await container.aresolve(Session)
            assert session.id == "async-session"
            assert cleanup_events == []

        # Give the scheduled task time to run
        await asyncio.sleep(0.01)
        assert cleanup_events == ["cleaned_async"]

    def test_clear_scope_closes_async_exit_stacks_without_running_loop(
        self,
        container: Container,
    ) -> None:
        """clear_scope() closes async exit stacks when no event loop is running."""
        cleanup_events: list[str] = []

        async def async_session_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="async-session")
            finally:
                cleanup_events.append("cleaned_async_no_loop")

        container.register(
            Session,
            factory=async_session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        # Create and run in a manual event loop, then close it before scope exits
        loop = asyncio.new_event_loop()

        async def resolve_in_scope() -> None:
            with container.enter_scope("test"):
                session = await container.aresolve(Session)
                assert session.id == "async-session"
                # Note: scope will be cleared after exiting 'with' but before loop closes

        # Run the coroutine - scope cleanup happens inside run()
        loop.run_until_complete(resolve_in_scope())

        # At this point, the scope cleanup should have run via loop.create_task
        # Let the event loop process pending tasks before closing
        loop.run_until_complete(asyncio.sleep(0.01))
        loop.close()

        assert cleanup_events == ["cleaned_async_no_loop"]

    def test_async_generator_finally_block_runs_via_clear_scope(self, container: Container) -> None:
        """Async generator's finally block runs when clear_scope() is called."""
        events: list[str] = []

        async def resource_factory() -> AsyncGenerator[Session, None]:
            events.append("setup")
            try:
                yield Session(id="resource")
            finally:
                events.append("finally")

        container.register(
            Session,
            factory=resource_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async def run_test() -> None:
            with container.enter_scope("test"):
                session = await container.aresolve(Session)
                assert session.id == "resource"
                events.append("used")

            # Give the scheduled task time to run
            await asyncio.sleep(0.01)

        asyncio.run(run_test())
        assert events == ["setup", "used", "finally"]

    def test_clear_scope_handles_missing_async_exit_stack(self, container: Container) -> None:
        """clear_scope() handles case where no async exit stack exists."""

        # Only use sync factory, no async generators
        def sync_session_factory() -> Session:
            return Session(id="sync-session")

        container.register(
            Session,
            factory=sync_session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        # Should not raise any error even though no async exit stack exists
        with container.enter_scope("test"):
            session = container.resolve(Session)
            assert session.id == "sync-session"

    def test_clear_scope_closes_multiple_async_generators(self, container: Container) -> None:
        """clear_scope() closes all async generators in the scope."""
        cleanup_events: list[str] = []

        @dataclass
        class ResourceA:
            id: str

        @dataclass
        class ResourceB:
            id: str

        @dataclass
        class ResourceC:
            id: str

        async def resource_a_factory() -> AsyncGenerator[ResourceA, None]:
            try:
                yield ResourceA(id="a")
            finally:
                cleanup_events.append("cleaned_a")

        async def resource_b_factory() -> AsyncGenerator[ResourceB, None]:
            try:
                yield ResourceB(id="b")
            finally:
                cleanup_events.append("cleaned_b")

        async def resource_c_factory() -> AsyncGenerator[ResourceC, None]:
            try:
                yield ResourceC(id="c")
            finally:
                cleanup_events.append("cleaned_c")

        container.register(
            ResourceA,
            factory=resource_a_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            ResourceB,
            factory=resource_b_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            ResourceC,
            factory=resource_c_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async def run_test() -> None:
            with container.enter_scope("test"):
                a = await container.aresolve(ResourceA)
                b = await container.aresolve(ResourceB)
                c = await container.aresolve(ResourceC)
                assert a.id == "a"
                assert b.id == "b"
                assert c.id == "c"

            # Give the scheduled task time to run
            await asyncio.sleep(0.01)

        asyncio.run(run_test())
        # All three should be cleaned up (order may vary due to AsyncExitStack LIFO)
        assert sorted(cleanup_events) == ["cleaned_a", "cleaned_b", "cleaned_c"]

    def test_clear_scope_raises_error_when_no_event_loop(self, container: Container) -> None:
        """clear_scope() raises error when async cleanup needed but no event loop."""

        async def async_session_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="async-session")
            finally:
                pass  # Cleanup would happen here

        container.register(
            Session,
            factory=async_session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        # Test that the error is raised when no event loop is running

        def run_outside_async() -> None:
            # Create a new event loop, resolve, close the loop, then exit scope
            loop = asyncio.new_event_loop()

            scope = container.enter_scope("test")
            scope.__enter__()

            async def resolve() -> Session:
                return await container.aresolve(Session)

            session = loop.run_until_complete(resolve())
            assert session.id == "async-session"

            # Now close the loop so clear_scope will have no event loop
            loop.close()

            # Exiting scope should raise because no event loop is available for cleanup
            with pytest.raises(DIWireAsyncCleanupWithoutEventLoopError, match="test"):
                scope.__exit__(None, None, None)

        run_outside_async()


class TestImperativeScopeManagement:
    """Tests for imperative scope management (enter_scope without with blocks)."""

    def test_enter_scope_activates_immediately(self, container: Container) -> None:
        """enter_scope() activates the scope immediately."""
        assert _current_scope.get() is None

        scope = container.enter_scope("test")
        # Scope should be active immediately
        current = _current_scope.get()
        assert current is not None
        assert current.contains_scope("test")

        scope.close()
        assert _current_scope.get() is None

    def test_imperative_scope_sync_resolve(self, container: Container) -> None:
        """Imperative scope works with sync resolve."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        container.enter_scope("request")
        session1 = container.resolve(Session)
        session2 = container.resolve(Session)

        assert session1.id == session2.id
        container.close()

    def test_imperative_scope_async_resolve(self, container: Container) -> None:
        """Imperative scope works with async resolve."""
        container.register(Session, scope="app", lifetime=Lifetime.SCOPED)

        async def run_test() -> None:
            container.enter_scope("app")
            session1 = await container.aresolve(Session)
            session2 = await container.aresolve(Session)

            assert session1.id == session2.id
            await container.aclose()

        asyncio.run(run_test())

    def test_backward_compatibility_with_context_manager(self, container: Container) -> None:
        """Context manager usage still works (with is now no-op for entry)."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        with container.enter_scope("test") as scope:
            session = container.resolve(Session)
            assert isinstance(session, Session)
            assert _current_scope.get() is not None

        # Context manager exit should close the scope
        assert _current_scope.get() is None

    def test_nested_imperative_scopes(self, container: Container) -> None:
        """Nested imperative scopes work correctly."""
        container.register(Session, scope="parent", lifetime=Lifetime.SCOPED)
        container.register(Service, scope="child", lifetime=Lifetime.SCOPED)

        parent_scope = container.enter_scope("parent")
        current = _current_scope.get()
        assert current is not None
        assert current.contains_scope("parent")

        child_scope = container.enter_scope("child")
        current = _current_scope.get()
        assert current is not None
        assert current.contains_scope("parent")
        assert current.contains_scope("child")

        child_scope.close()
        current = _current_scope.get()
        assert current is not None
        assert current.contains_scope("parent")
        assert not current.contains_scope("child")

        parent_scope.close()
        assert _current_scope.get() is None

    def test_container_close_closes_all_scopes_lifo(self, container: Container) -> None:
        """container.close() closes all scopes in LIFO order."""
        close_order: list[str] = []

        container.register(Session, scope="first", lifetime=Lifetime.SCOPED)
        container.register(Service, scope="second", lifetime=Lifetime.SCOPED)

        scope1 = container.enter_scope("first")
        scope2 = container.enter_scope("second")

        # Both scopes should be active
        assert not scope1._exited
        assert not scope2._exited

        container.close()

        # Both scopes should be closed
        assert scope1._exited
        assert scope2._exited  # type: ignore[unreachable]

    def test_individual_scope_close(self, container: Container) -> None:
        """ScopedContainer.close() closes a specific scope."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        scope = container.enter_scope("test")
        container.resolve(Session)

        assert not scope._exited
        assert len(container._scoped_instances) > 0

        scope.close()

        assert scope._exited
        assert len(container._scoped_instances) == 0  # type: ignore[unreachable]

    def test_individual_scope_aclose(self, container: Container) -> None:
        """ScopedContainer.aclose() closes a specific scope asynchronously."""
        cleanup_called = False

        async def session_factory() -> AsyncGenerator[Session, None]:
            nonlocal cleanup_called
            try:
                yield Session(id="async-session")
            finally:
                cleanup_called = True

        container.register(
            Session,
            factory=session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async def run_test() -> None:
            scope = container.enter_scope("test")
            session = await container.aresolve(Session)
            assert session.id == "async-session"

            assert not scope._exited
            await scope.aclose()
            assert scope._exited

        asyncio.run(run_test())
        assert cleanup_called

    def test_idempotent_scope_close(self, container: Container) -> None:
        """Calling close() multiple times on a scope is safe."""
        scope = container.enter_scope("test")

        scope.close()
        assert scope._exited

        # Should not raise
        scope.close()
        scope.close()
        assert scope._exited

    def test_idempotent_container_close(self, container: Container) -> None:
        """Calling close() multiple times on a container is safe."""
        container.enter_scope("test")

        container.close()
        assert container._closed

        # Should not raise
        container.close()
        container.close()
        assert container._closed

    def test_idempotent_scope_aclose(self, container: Container) -> None:
        """Calling aclose() multiple times on a scope is safe."""

        async def run_test() -> None:
            scope = container.enter_scope("test")

            await scope.aclose()
            assert scope._exited

            # Should not raise
            await scope.aclose()
            await scope.aclose()
            assert scope._exited

        asyncio.run(run_test())

    def test_idempotent_container_aclose(self, container: Container) -> None:
        """Calling aclose() multiple times on a container is safe."""

        async def run_test() -> None:
            container.enter_scope("test")

            await container.aclose()
            assert container._closed

            # Should not raise
            await container.aclose()
            await container.aclose()
            assert container._closed

        asyncio.run(run_test())

    def test_close_without_scopes(self, container: Container) -> None:
        """container.close() with no active scopes is safe."""
        container.close()
        assert container._closed

    def test_mixed_imperative_and_context_manager(self, container: Container) -> None:
        """Imperative and context manager usage can be mixed."""
        container.register(Session, scope="outer", lifetime=Lifetime.SCOPED)
        container.register(Service, scope="inner", lifetime=Lifetime.SCOPED)

        outer_scope = container.enter_scope("outer")

        with container.enter_scope("inner"):
            current = _current_scope.get()
            assert current is not None
            assert current.contains_scope("outer")
            assert current.contains_scope("inner")

        # Inner scope is closed by context manager
        current = _current_scope.get()
        assert current is not None
        assert current.contains_scope("outer")
        assert not current.contains_scope("inner")

        outer_scope.close()
        assert _current_scope.get() is None

    def test_close_scope_closes_named_scope(self, container: Container) -> None:
        """close_scope() closes a scope by name."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        scope = container.enter_scope("request")
        container.resolve(Session)

        assert not scope._exited
        container.close_scope("request")
        assert scope._exited

    def test_close_scope_closes_child_scopes(self, container: Container) -> None:
        """close_scope() closes child scopes first (LIFO order)."""
        container.register(Session, scope="app", lifetime=Lifetime.SCOPED)
        container.register(Service, scope="session", lifetime=Lifetime.SCOPED)

        # Create hierarchy: app -> session -> request
        app_scope = container.enter_scope("app")
        session_scope = container.enter_scope("session")
        request_scope = container.enter_scope("request")

        # All scopes should be active
        assert not app_scope._exited
        assert not session_scope._exited
        assert not request_scope._exited

        # Close "session" should close both "session" and "request" (child)
        container.close_scope("session")

        assert not app_scope._exited  # app should still be open
        assert session_scope._exited  # session should be closed
        assert request_scope._exited  # type: ignore[unreachable]  # request (child) closed

        # Current scope should be app
        current = _current_scope.get()
        assert current is not None
        assert current.contains_scope("app")
        assert not current.contains_scope("session")

        app_scope.close()

    def test_close_scope_leaves_unrelated_scopes_open(self, container: Container) -> None:
        """close_scope() does not affect scopes without the specified name."""
        container.register(Session, scope="db", lifetime=Lifetime.SCOPED)

        # Create two independent scopes
        db_scope = container.enter_scope("db")
        request_scope = container.enter_scope("request")

        assert not db_scope._exited
        assert not request_scope._exited

        # Close "request" should not affect "db"
        container.close_scope("request")

        assert request_scope._exited
        assert not db_scope._exited  # type: ignore[unreachable]

        db_scope.close()

    def test_close_scope_with_nonexistent_scope(self, container: Container) -> None:
        """close_scope() with nonexistent scope name is a no-op."""
        scope = container.enter_scope("test")
        assert not scope._exited

        # Should not raise and should not close any scopes
        container.close_scope("nonexistent")

        assert not scope._exited
        scope.close()

    def test_aclose_scope_closes_child_scopes(self, container: Container) -> None:
        """aclose_scope() closes child scopes with async cleanup."""
        cleanup_order: list[str] = []

        async def session_factory() -> AsyncGenerator[Session, None]:
            try:
                yield Session(id="session")
            finally:
                cleanup_order.append("session")

        async def request_factory() -> AsyncGenerator[Service, None]:
            try:
                yield Service(session=Session(id="request"))
            finally:
                cleanup_order.append("request")

        container.register(
            Session,
            factory=session_factory,
            scope="session",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Service,
            factory=request_factory,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        async def run_test() -> None:
            app_scope = container.enter_scope("app")
            session_scope = container.enter_scope("session")
            await container.aresolve(Session)
            request_scope = container.enter_scope("request")
            await container.aresolve(Service)

            # Close session scope and its children
            await container.aclose_scope("session")

            # Request (child) should be cleaned up before session (parent)
            assert cleanup_order == ["request", "session"]
            assert not app_scope._exited
            assert session_scope._exited
            assert request_scope._exited

            app_scope.close()

        asyncio.run(run_test())

    def test_close_scope_lifo_order(self, container: Container) -> None:
        """close_scope() closes scopes in LIFO order (children first)."""
        close_order: list[str] = []

        def session_factory() -> Generator[Session, None, None]:
            try:
                yield Session(id="session")
            finally:
                close_order.append("session")

        def request_factory() -> Generator[Service, None, None]:
            try:
                yield Service(session=Session(id="request"))
            finally:
                close_order.append("request")

        container.register(
            Session,
            factory=session_factory,
            scope="session",
            lifetime=Lifetime.SCOPED,
        )
        container.register(
            Service,
            factory=request_factory,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        session_scope = container.enter_scope("session")
        container.resolve(Session)
        request_scope = container.enter_scope("request")
        container.resolve(Service)

        container.close_scope("session")

        # Request (child) should close before session (parent)
        assert close_order == ["request", "session"]
        assert session_scope._exited
        assert request_scope._exited

    def test_close_scope_with_resources(self, container: Container) -> None:
        """close_scope() properly cleans up generator factory resources."""
        cleanup_called = False

        def session_factory() -> Generator[Session, None, None]:
            nonlocal cleanup_called
            try:
                yield Session(id="gen-session")
            finally:
                cleanup_called = True

        container.register(
            Session,
            factory=session_factory,
            scope="request",
            lifetime=Lifetime.SCOPED,
        )

        container.enter_scope("request")
        session = container.resolve(Session)
        assert session.id == "gen-session"
        assert not cleanup_called

        container.close_scope("request")
        assert cleanup_called

    def test_close_scope_failure_keeps_scope_in_active_scopes(self, container: Container) -> None:
        """If scope.close() fails, the scope remains in _active_scopes."""
        from unittest.mock import patch

        scope = container.enter_scope("test")
        assert len(container._active_scopes) == 1

        with patch.object(scope, "close", side_effect=RuntimeError("close failed")):
            with pytest.raises(RuntimeError, match="close failed"):
                container.close()

        # Scope should remain in _active_scopes after failure
        assert len(container._active_scopes) == 1
        assert container._active_scopes[0] is scope

        # Cleanup: properly close the scope to reset _current_scope
        scope.close()

    def test_aclose_scope_failure_keeps_scope_in_active_scopes(self, container: Container) -> None:
        """If scope.aclose() fails, the scope remains in _active_scopes."""
        from unittest.mock import AsyncMock, patch

        async def run_test() -> None:
            scope = container.enter_scope("test")
            assert len(container._active_scopes) == 1

            mock_aclose = AsyncMock(side_effect=RuntimeError("aclose failed"))
            with patch.object(scope, "aclose", mock_aclose):
                with pytest.raises(RuntimeError, match="aclose failed"):
                    await container.aclose()

            # Scope should remain in _active_scopes after failure
            assert len(container._active_scopes) == 1
            assert container._active_scopes[0] is scope

            # Cleanup: properly close the scope to reset _current_scope
            await scope.aclose()

        asyncio.run(run_test())

    def test_aclose_drains_remaining_scopes_when_already_closed(self, container: Container) -> None:
        """aclose() drains remaining scopes even if container is already closed."""

        async def run_test() -> None:
            scope1 = container.enter_scope("first")
            scope2 = container.enter_scope("second")

            # Mark container as closed without draining scopes
            container._closed = True
            assert len(container._active_scopes) == 2

            # aclose() should still drain remaining scopes
            await container.aclose()

            assert len(container._active_scopes) == 0
            assert scope1._exited
            assert scope2._exited

        asyncio.run(run_test())

    def test_close_handles_concurrent_scope_removal(self, container: Container) -> None:
        """close() handles race condition where scope is removed between peek and pop."""
        scope = container.enter_scope("test")

        # Simulate race condition: clear _active_scopes after close() but before pop
        original_close = scope.close

        def close_and_clear() -> None:
            original_close()
            container._active_scopes.clear()

        scope.close = close_and_clear  # type: ignore[method-assign]

        # Should not raise even though scope was removed between close and pop
        container.close()
        assert len(container._active_scopes) == 0

    def test_aclose_handles_concurrent_scope_removal(self, container: Container) -> None:
        """aclose() handles race condition where scope is removed between peek and pop."""

        async def run_test() -> None:
            scope = container.enter_scope("test")

            # Simulate race: clear _active_scopes after aclose() but before pop
            original_aclose = scope.aclose

            async def aclose_and_clear() -> None:
                await original_aclose()
                container._active_scopes.clear()

            scope.aclose = aclose_and_clear  # type: ignore[method-assign]

            # Should not raise even though scope was removed between close and pop
            await container.aclose()
            assert len(container._active_scopes) == 0

        asyncio.run(run_test())

    def test_close_pops_scope_when_unregister_skipped(self, container: Container) -> None:
        """close() pops scope when _unregister_active_scope doesn't remove it."""
        scope = container.enter_scope("test")
        assert len(container._active_scopes) == 1

        # Override _close_sync to skip _unregister_active_scope
        # This simulates scenario where Container.close() needs to pop
        original_close_sync = scope._close_sync

        def close_without_unregister() -> None:
            if scope._exited:
                return
            import contextlib

            with contextlib.suppress(ValueError, RuntimeError):
                _current_scope.reset(scope._token)
            scope._container._clear_scope(scope._scope_id)
            # Deliberately skip _unregister_active_scope
            scope._exited = True

        scope._close_sync = close_without_unregister  # type: ignore[method-assign]
        container.close()

        # Container.close() should have popped the scope
        assert len(container._active_scopes) == 0

    def test_aclose_pops_scope_when_unregister_skipped(self, container: Container) -> None:
        """aclose() pops scope when _unregister_active_scope doesn't remove it."""

        async def run_test() -> None:
            scope = container.enter_scope("test")
            assert len(container._active_scopes) == 1

            # Override _close_async to skip _unregister_active_scope
            async def aclose_without_unregister() -> None:
                if scope._exited:
                    return
                import contextlib

                with contextlib.suppress(ValueError, RuntimeError):
                    _current_scope.reset(scope._token)
                await scope._container._aclear_scope(scope._scope_id)
                # Deliberately skip _unregister_active_scope
                scope._exited = True

            scope._close_async = aclose_without_unregister  # type: ignore[method-assign]
            await container.aclose()

            # Container.aclose() should have popped the scope
            assert len(container._active_scopes) == 0

        asyncio.run(run_test())


class TestContainerClosedError:
    """Tests for DIWireContainerClosedError after container.close()."""

    def test_resolve_after_close_raises_error(self, container: Container) -> None:
        """resolve() after close() raises DIWireContainerClosedError."""
        from diwire.exceptions import DIWireContainerClosedError

        container.close()

        with pytest.raises(DIWireContainerClosedError, match="closed container"):
            container.resolve(Session)

    def test_aresolve_after_close_raises_error(self, container: Container) -> None:
        """aresolve() after close() raises DIWireContainerClosedError."""
        from diwire.exceptions import DIWireContainerClosedError

        container.close()

        async def run_test() -> None:
            with pytest.raises(DIWireContainerClosedError, match="closed container"):
                await container.aresolve(Session)

        asyncio.run(run_test())

    def test_enter_scope_after_close_raises_error(self, container: Container) -> None:
        """enter_scope() after close() raises DIWireContainerClosedError."""
        from diwire.exceptions import DIWireContainerClosedError

        container.close()

        with pytest.raises(DIWireContainerClosedError, match="closed container"):
            container.enter_scope("test")

    def test_register_active_scope_on_closed_container_raises_error(
        self,
        container: Container,
    ) -> None:
        """Directly creating ScopedContainer on closed container raises error."""
        from diwire.container_scopes import _ScopeId
        from diwire.exceptions import DIWireContainerClosedError

        container.close()

        scope_id = _ScopeId(segments=((None, 1),))

        with pytest.raises(DIWireContainerClosedError, match="closed container"):
            ScopedContainer(container, scope_id)


class TestImperativeScopeResourceCleanup:
    """Tests for resource cleanup with imperative scope management."""

    def test_generator_cleanup_on_scope_close(self, container: Container) -> None:
        """Generator factories are cleaned up on scope.close()."""
        cleanup_called = False

        def session_factory() -> Generator[Session, None, None]:
            nonlocal cleanup_called
            try:
                yield Session(id="gen-session")
            finally:
                cleanup_called = True

        container.register(
            Session,
            factory=session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        scope = container.enter_scope("test")
        session = container.resolve(Session)
        assert session.id == "gen-session"
        assert not cleanup_called

        scope.close()
        assert cleanup_called

    def test_async_generator_cleanup_on_scope_aclose(self, container: Container) -> None:
        """Async generator factories are cleaned up on scope.aclose()."""
        cleanup_called = False

        async def session_factory() -> AsyncGenerator[Session, None]:
            nonlocal cleanup_called
            try:
                yield Session(id="async-gen-session")
            finally:
                cleanup_called = True

        container.register(
            Session,
            factory=session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async def run_test() -> None:
            scope = container.enter_scope("test")
            session = await container.aresolve(Session)
            assert session.id == "async-gen-session"
            assert not cleanup_called

            await scope.aclose()
            assert cleanup_called

        asyncio.run(run_test())

    def test_generator_cleanup_on_container_close(self, container: Container) -> None:
        """Generator factories are cleaned up on container.close()."""
        cleanup_called = False

        def session_factory() -> Generator[Session, None, None]:
            nonlocal cleanup_called
            try:
                yield Session(id="gen-session")
            finally:
                cleanup_called = True

        container.register(
            Session,
            factory=session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        container.enter_scope("test")
        session = container.resolve(Session)
        assert session.id == "gen-session"
        assert not cleanup_called

        container.close()
        assert cleanup_called

    def test_async_generator_cleanup_on_container_aclose(self, container: Container) -> None:
        """Async generator factories are cleaned up on container.aclose()."""
        cleanup_called = False

        async def session_factory() -> AsyncGenerator[Session, None]:
            nonlocal cleanup_called
            try:
                yield Session(id="async-gen-session")
            finally:
                cleanup_called = True

        container.register(
            Session,
            factory=session_factory,
            scope="test",
            lifetime=Lifetime.SCOPED,
        )

        async def run_test() -> None:
            container.enter_scope("test")
            session = await container.aresolve(Session)
            assert session.id == "async-gen-session"
            assert not cleanup_called

            await container.aclose()
            assert cleanup_called

        asyncio.run(run_test())

    def test_scoped_instances_cleared_on_close(self, container: Container) -> None:
        """_scoped_instances is empty after close()."""
        container.register(Session, scope="test", lifetime=Lifetime.SCOPED)

        container.enter_scope("test")
        container.resolve(Session)

        assert len(container._scoped_instances) > 0

        container.close()

        assert len(container._scoped_instances) == 0


class TestImperativeScopeConcurrency:
    """Tests for thread safety of imperative scope management."""

    def test_concurrent_scope_operations(self, container: Container) -> None:
        """Concurrent scope operations are thread-safe."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        results: list[str] = []
        errors: list[Exception] = []

        def worker(worker_id: int) -> None:
            try:
                scope = container.enter_scope("request")
                session = container.resolve(Session)
                results.append(f"{worker_id}:{session.id}")
                scope.close()
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            for future in futures:
                future.result()

        assert len(errors) == 0
        assert len(results) == 10

    def test_async_concurrent_scopes(self, container: Container) -> None:
        """Async concurrent scope operations work correctly."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        async def run_test() -> None:
            results: list[str] = []

            async def worker(worker_id: int) -> None:
                scope = container.enter_scope("request")
                session = await container.aresolve(Session)
                results.append(f"{worker_id}:{session.id}")
                await scope.aclose()

            await asyncio.gather(*[worker(i) for i in range(10)])

            assert len(results) == 10

        asyncio.run(run_test())


class TestImperativeScopedSingletons:
    """Tests for scoped singleton behavior with imperative scope management."""

    def test_instance_sharing_within_scope(self, container: Container) -> None:
        """Scoped singletons share instances within a scope."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        container.enter_scope("request")
        session1 = container.resolve(Session)
        session2 = container.resolve(Session)

        assert session1.id == session2.id
        container.close()

    def test_instance_isolation_between_scopes(self, container: Container) -> None:
        """Different scopes have different scoped singleton instances."""
        container.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        # First scope
        scope1 = container.enter_scope("request")
        session1 = container.resolve(Session)
        scope1.close()

        # Create a new container since the first one is now closed
        container2 = Container()
        container2.register(Session, scope="request", lifetime=Lifetime.SCOPED)

        # Second scope
        scope2 = container2.enter_scope("request")
        session2 = container2.resolve(Session)
        scope2.close()

        # Different scopes should have different instances
        assert session1.id != session2.id
