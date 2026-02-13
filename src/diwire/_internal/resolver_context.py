from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast, overload

from diwire._internal.injection import (
    INJECT_CONTEXT_KWARG,
    INJECT_RESOLVER_KWARG,
    INJECT_WRAPPER_MARKER,
    InjectedCallableInspector,
)
from diwire._internal.policies import DependencyRegistrationPolicy
from diwire._internal.resolvers.protocol import ResolverProtocol
from diwire._internal.scope import BaseScope
from diwire.exceptions import DIWireInvalidRegistrationError, DIWireResolverNotSetError

if TYPE_CHECKING:
    from typing_extensions import Self

    from diwire._internal.container import Container


T = TypeVar("T")
InjectableF = TypeVar("InjectableF", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class _InjectInvocationState:
    source: Literal["explicit", "context", "fallback"]
    context_resolver: ResolverProtocol | None


@dataclass(frozen=True, slots=True)
class _InjectWrapperConfig:
    callable_obj: Callable[..., Any]
    scope: BaseScope | None
    dependency_registration_policy: DependencyRegistrationPolicy | None
    auto_open_scope: bool


class _ResolverBoundResolver:
    """Resolver wrapper that synchronizes resolver context with ResolverContext."""

    def __init__(
        self,
        *,
        resolver: ResolverProtocol,
        resolver_context: ResolverContext,
        push_resolver: Callable[[ResolverProtocol], None],
        pop_resolver: Callable[[], None],
    ) -> None:
        self._resolver = resolver
        self._resolver_context = resolver_context
        self._push_resolver = push_resolver
        self._pop_resolver = pop_resolver

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolver, name)

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        return self._resolver.resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        return await self._resolver.aresolve(dependency)

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> _ResolverBoundResolver:
        scoped_resolver = self._resolver.enter_scope(scope, context=context)
        if scoped_resolver is self._resolver:
            return self
        return _ResolverBoundResolver(
            resolver=scoped_resolver,
            resolver_context=self._resolver_context,
            push_resolver=self._push_resolver,
            pop_resolver=self._pop_resolver,
        )

    def __enter__(self) -> Self:
        self._resolver.__enter__()
        self._push_resolver(cast("ResolverProtocol", self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self._resolver.__exit__(exc_type, exc_value, traceback)
        finally:
            self._pop_resolver()

    async def __aenter__(self) -> Self:
        await cast("Any", self._resolver).__aenter__()
        self._push_resolver(cast("ResolverProtocol", self))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self._resolver.__aexit__(exc_type, exc_value, traceback)
        finally:
            self._pop_resolver()

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        self._resolver.close(exc_type, exc_value, traceback)

    async def aclose(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self._resolver.aclose(exc_type, exc_value, traceback)


class ResolverContext:
    """Task/thread-safe context for resolver-bound injection and resolution."""

    __slots__ = (
        "_current_resolver_var",
        "_fallback_container",
        "_injected_callable_inspector",
        "_token_stack_var",
    )

    def __init__(self) -> None:
        self._current_resolver_var: ContextVar[ResolverProtocol | None] = ContextVar(
            "diwire_resolver_context_resolver",
            default=None,
        )
        self._token_stack_var: ContextVar[tuple[Token[ResolverProtocol | None], ...]] = ContextVar(
            "diwire_resolver_context_tokens",
            default=(),
        )
        self._fallback_container: Container | None = None
        self._injected_callable_inspector = InjectedCallableInspector()

    def set_fallback_container(self, container: Container) -> None:
        """Set the fallback container used when no resolver is bound.

        Resolver-bound contexts always take precedence over this fallback.

        Args:
            container: Container used to compile fallback resolvers and injected
                callables when no context resolver is active.

        """
        self._set_fallback_container(container)

    def _push(self, resolver: ResolverProtocol) -> None:
        token = self._current_resolver_var.set(resolver)
        tokens = self._token_stack_var.get()
        self._token_stack_var.set((*tokens, token))

    def _pop(self) -> None:
        tokens = self._token_stack_var.get()
        if not tokens:
            return
        token = tokens[-1]
        self._token_stack_var.set(tokens[:-1])
        self._current_resolver_var.reset(token)

    def _set_fallback_container(self, container: Container) -> None:
        self._fallback_container = container

    def _get_bound_resolver_or_none(self) -> ResolverProtocol | None:
        return self._current_resolver_var.get()

    def _require_context_or_fallback_resolver(self) -> ResolverProtocol:
        resolver = self._get_bound_resolver_or_none()
        if resolver is not None:
            return resolver

        fallback_resolver = self._get_fallback_resolver_or_none()
        if fallback_resolver is not None:
            return fallback_resolver

        msg = (
            "Resolver is not set for resolver_context. Enter a compiled resolver context "
            "before using resolver_context."
        )
        raise DIWireResolverNotSetError(msg)

    def _get_fallback_resolver_or_none(self) -> ResolverProtocol | None:
        fallback_container = self._fallback_container
        if fallback_container is None:
            return None

        fallback_resolver = fallback_container.compile()
        return self._wrap_resolver(fallback_resolver)

    def _wrap_resolver(self, resolver: ResolverProtocol) -> ResolverProtocol:
        resolver_any = cast("Any", resolver)
        if isinstance(resolver_any, _ResolverBoundResolver):
            return cast("ResolverProtocol", resolver_any)
        return cast(
            "ResolverProtocol",
            _ResolverBoundResolver(
                resolver=resolver,
                resolver_context=self,
                push_resolver=self._push,
                pop_resolver=self._pop,
            ),
        )

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        """Resolve a dependency from the active resolver or fallback container.

        Args:
            dependency: Dependency key to resolve.

        Raises:
            DIWireResolverNotSetError: If no resolver is bound and no fallback
                container is configured.

        """
        return self._require_context_or_fallback_resolver().resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        """Asynchronously resolve a dependency from context or fallback.

        Args:
            dependency: Dependency key to resolve.

        Raises:
            DIWireResolverNotSetError: If no resolver is bound and no fallback
                container is configured.

        """
        return await self._require_context_or_fallback_resolver().aresolve(dependency)

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
        """Enter a child scope on the active resolver or fallback resolver.

        Args:
            scope: Target scope to enter. ``None`` keeps the current scope.
            context: Optional context payload merged into the entered scope.

        Raises:
            DIWireResolverNotSetError: If no resolver is bound and no fallback
                container is configured.

        """
        return self._require_context_or_fallback_resolver().enter_scope(scope, context=context)

    @overload
    def inject(self, func: InjectableF) -> InjectableF: ...

    @overload
    def inject(
        self,
        func: Literal["from_decorator"] = "from_decorator",
        *,
        scope: BaseScope | Literal["infer"] = "infer",
        dependency_registration_policy: (
            DependencyRegistrationPolicy | Literal["from_container"]
        ) = "from_container",
        auto_open_scope: bool = True,
    ) -> Callable[[InjectableF], InjectableF]: ...

    def inject(
        self,
        func: InjectableF | Literal["from_decorator"] = "from_decorator",
        *,
        scope: BaseScope | Literal["infer"] = "infer",
        dependency_registration_policy: (
            DependencyRegistrationPolicy | Literal["from_container"]
        ) = "from_container",
        auto_open_scope: bool = True,
    ) -> InjectableF | Callable[[InjectableF], InjectableF]:
        """Wrap callables so ``Injected[...]`` parameters resolve at invocation.

        Resolution precedence at call time is explicit ``diwire_resolver``,
        then an active context-bound resolver, then the configured fallback
        container when it is configured with ``use_resolver_context=True``.

        Args:
            func: Callable to wrap directly, or ``"from_decorator"`` when used
                as ``@resolver_context.inject(...)``.
            scope: Explicit scope for wrapper generation, or ``"infer"`` to
                infer from injected dependencies.
            dependency_registration_policy: Dependency autoregistration policy for
                wrapper generation, or ``"from_container"`` to inherit the
                fallback container setting.
            auto_open_scope: Whether invocation should auto-enter scopes when
                needed. When ``True`` (default), scope entry is attempted only
                when moving into a deeper target scope is valid and required.
                If the target scope is already open, no additional scope is
                entered. If the current resolver is already deeper than the
                target scope, no additional scope is entered and resolution
                proceeds from the current resolver (including its existing
                scope-context chain).

        Raises:
            DIWireInvalidRegistrationError: If inject configuration values are
                invalid, ``func`` is not callable, or the callable uses
                reserved parameter names.
            DIWireResolverNotSetError: If invocation has no explicit resolver,
                no active context resolver, and no fallback container eligible
                for inject fallback.

        """
        resolved_scope = self._resolve_inject_scope(scope)
        resolved_dependency_registration_policy = (
            self._resolve_inject_dependency_registration_policy(
                dependency_registration_policy=dependency_registration_policy,
            )
        )

        def decorator(callable_obj: InjectableF) -> InjectableF:
            self._validate_injected_callable_signature(callable_obj)
            inspected_callable = self._injected_callable_inspector.inspect_callable(callable_obj)
            cache: dict[Container, Callable[..., Any]] = {}
            wrapper_config = _InjectWrapperConfig(
                callable_obj=callable_obj,
                scope=resolved_scope,
                dependency_registration_policy=resolved_dependency_registration_policy,
                auto_open_scope=auto_open_scope,
            )
            fallback_container = self._fallback_container
            if fallback_container is not None:
                self._get_cached_injected_callable(
                    cache=cache,
                    container=fallback_container,
                    wrapper_config=wrapper_config,
                )

            invocation = self._build_injection_invoker(
                cache=cache,
                wrapper_config=wrapper_config,
            )
            wrapped_callable = self._wrap_injected_callable(
                callable_obj=callable_obj,
                invocation=invocation,
            )
            wrapped_callable.__signature__ = inspected_callable.public_signature  # type: ignore[attr-defined]
            wrapped_callable.__dict__[INJECT_WRAPPER_MARKER] = True
            return cast("InjectableF", wrapped_callable)

        func_value = cast("Any", func)
        if func_value == "from_decorator":
            return decorator
        if not callable(func_value):
            msg = "inject() parameter 'func' must be callable or 'from_decorator'."
            raise DIWireInvalidRegistrationError(msg)
        return decorator(func_value)

    def _resolve_inject_scope(
        self,
        scope: BaseScope | Literal["infer"],
    ) -> BaseScope | None:
        scope_value = cast("Any", scope)
        if scope_value == "infer":
            return None
        if isinstance(scope_value, BaseScope):
            return scope_value
        msg = "inject() parameter 'scope' must be BaseScope or 'infer'."
        raise DIWireInvalidRegistrationError(msg)

    def _resolve_inject_dependency_registration_policy(
        self,
        *,
        dependency_registration_policy: (DependencyRegistrationPolicy | Literal["from_container"]),
    ) -> DependencyRegistrationPolicy | None:
        dependency_registration_policy_value = cast("Any", dependency_registration_policy)
        if dependency_registration_policy_value == "from_container":
            return None
        if isinstance(dependency_registration_policy_value, DependencyRegistrationPolicy):
            return dependency_registration_policy_value
        msg = (
            "inject() parameter 'dependency_registration_policy' must be "
            "DependencyRegistrationPolicy or 'from_container'."
        )
        raise DIWireInvalidRegistrationError(msg)

    def _validate_injected_callable_signature(self, callable_obj: Callable[..., Any]) -> None:
        signature = inspect.signature(callable_obj)
        if INJECT_RESOLVER_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved "
                f"parameter '{INJECT_RESOLVER_KWARG}'."
            )
            raise DIWireInvalidRegistrationError(msg)
        if INJECT_CONTEXT_KWARG in signature.parameters:
            msg = (
                f"Callable '{self._callable_name(callable_obj)}' cannot declare reserved "
                f"parameter '{INJECT_CONTEXT_KWARG}'."
            )
            raise DIWireInvalidRegistrationError(msg)

    def _build_injection_invoker(
        self,
        *,
        cache: dict[Container, Callable[..., Any]],
        wrapper_config: _InjectWrapperConfig,
    ) -> Callable[..., Any]:
        def _invoke(*args: Any, **kwargs: Any) -> Any:
            state = self._resolve_injection_state(kwargs)
            fallback_container = self._require_inject_fallback_container()
            injected_callable = self._get_cached_injected_callable(
                cache=cache,
                container=fallback_container,
                wrapper_config=wrapper_config,
            )

            runtime_kwargs = kwargs
            if state.source == "context":
                runtime_kwargs = dict(kwargs)
                runtime_kwargs[INJECT_RESOLVER_KWARG] = cast(
                    "ResolverProtocol",
                    state.context_resolver,
                )
            return injected_callable(*args, **runtime_kwargs)

        return _invoke

    def _resolve_injection_state(self, kwargs: dict[str, Any]) -> _InjectInvocationState:
        if INJECT_RESOLVER_KWARG in kwargs:
            return _InjectInvocationState(source="explicit", context_resolver=None)

        context_resolver = self._get_bound_resolver_or_none()
        if context_resolver is not None:
            return _InjectInvocationState(source="context", context_resolver=context_resolver)

        fallback_container = self._fallback_container
        if fallback_container is not None:
            fallback_uses_resolver_context = bool(
                getattr(fallback_container, "_use_resolver_context", True)
            )
            if fallback_uses_resolver_context:
                fallback_container.compile()
                return _InjectInvocationState(source="fallback", context_resolver=None)

        msg = (
            "Resolver is not set for resolver_context.inject. Pass "
            f"'{INJECT_RESOLVER_KWARG}' explicitly, enter a resolver context, "
            "or initialize a fallback container with use_resolver_context=True."
        )
        raise DIWireResolverNotSetError(msg)

    def _require_inject_fallback_container(self) -> Container:
        fallback_container = self._fallback_container
        if fallback_container is None:
            msg = (
                "ResolverContext.inject requires a fallback container. Initialize a container "
                "with this ResolverContext before decorating callables."
            )
            raise DIWireResolverNotSetError(msg)
        return fallback_container

    def _get_cached_injected_callable(
        self,
        *,
        cache: dict[Container, Callable[..., Any]],
        container: Container,
        wrapper_config: _InjectWrapperConfig,
    ) -> Callable[..., Any]:
        injected_callable = cache.get(container)
        if injected_callable is not None:
            return injected_callable

        injected_callable = container._inject_callable(  # noqa: SLF001
            callable_obj=wrapper_config.callable_obj,
            scope=wrapper_config.scope,
            dependency_registration_policy=wrapper_config.dependency_registration_policy,
            auto_open_scope=wrapper_config.auto_open_scope,
        )
        cache[container] = injected_callable
        return injected_callable

    def _wrap_injected_callable(
        self,
        *,
        callable_obj: InjectableF,
        invocation: Callable[..., Any],
    ) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(callable_obj):

            @functools.wraps(callable_obj)
            async def _async_injected(*args: Any, **kwargs: Any) -> Any:
                result = invocation(*args, **kwargs)
                return await cast("Awaitable[Any]", result)

            return _async_injected

        @functools.wraps(callable_obj)
        def _sync_injected(*args: Any, **kwargs: Any) -> Any:
            return invocation(*args, **kwargs)

        return _sync_injected

    def _callable_name(self, callable_obj: Callable[..., Any]) -> str:
        return getattr(callable_obj, "__qualname__", repr(callable_obj))


resolver_context = ResolverContext()
