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
from diwire._internal.resolvers.protocol import ResolverProtocol
from diwire._internal.scope import BaseScope
from diwire.exceptions import DIWireInvalidRegistrationError, DIWireProviderNotSetError

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
    autoregister_dependencies: bool | None
    auto_open_scope: bool


class _ProviderBoundResolver:
    """Resolver wrapper that synchronizes resolver context with ProviderContext."""

    def __init__(
        self,
        *,
        resolver: ResolverProtocol,
        provider_context: ProviderContext,
    ) -> None:
        self._resolver = resolver
        self._provider_context = provider_context

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
    ) -> _ProviderBoundResolver:
        scoped_resolver = self._resolver.enter_scope(scope, context=context)
        if scoped_resolver is self._resolver:
            return self
        return _ProviderBoundResolver(
            resolver=scoped_resolver,
            provider_context=self._provider_context,
        )

    def __enter__(self) -> Self:
        self._resolver.__enter__()
        self._provider_context.push_resolver(cast("ResolverProtocol", self))
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
            self._provider_context.pop_resolver()

    async def __aenter__(self) -> Self:
        await cast("Any", self._resolver).__aenter__()
        self._provider_context.push_resolver(cast("ResolverProtocol", self))
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
            self._provider_context.pop_resolver()

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


class ProviderContext:
    """Task/thread-safe context for resolver-bound injection and resolution."""

    def __init__(self) -> None:
        self._current_resolver_var: ContextVar[ResolverProtocol | None] = ContextVar(
            "diwire_provider_context_resolver",
            default=None,
        )
        self._token_stack_var: ContextVar[tuple[Token[ResolverProtocol | None], ...]] = ContextVar(
            "diwire_provider_context_tokens",
            default=(),
        )
        self._fallback_container: Container | None = None
        self._injected_callable_inspector = InjectedCallableInspector()

    def push_resolver(self, resolver: ResolverProtocol) -> None:
        self._push(resolver)

    def pop_resolver(self) -> None:
        self._pop()

    def set_fallback_container(self, container: Container) -> None:
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
            "Provider is not set for provider_context. Enter a compiled resolver context "
            "before using provider_context."
        )
        raise DIWireProviderNotSetError(msg)

    def _get_fallback_resolver_or_none(self) -> ResolverProtocol | None:
        fallback_container = self._fallback_container
        if fallback_container is None:
            return None

        fallback_resolver = fallback_container.compile()
        fallback_resolver_any = cast("Any", fallback_resolver)
        if isinstance(fallback_resolver_any, _ProviderBoundResolver):
            return cast("ResolverProtocol", fallback_resolver_any)
        return cast(
            "ResolverProtocol",
            _ProviderBoundResolver(
                resolver=fallback_resolver,
                provider_context=self,
            ),
        )

    @overload
    def resolve(self, dependency: type[T]) -> T: ...

    @overload
    def resolve(self, dependency: Any) -> Any: ...

    def resolve(self, dependency: Any) -> Any:
        return self._require_context_or_fallback_resolver().resolve(dependency)

    @overload
    async def aresolve(self, dependency: type[T]) -> T: ...

    @overload
    async def aresolve(self, dependency: Any) -> Any: ...

    async def aresolve(self, dependency: Any) -> Any:
        return await self._require_context_or_fallback_resolver().aresolve(dependency)

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> ResolverProtocol:
        return self._require_context_or_fallback_resolver().enter_scope(scope, context=context)

    @overload
    def inject(self, func: InjectableF) -> InjectableF: ...

    @overload
    def inject(
        self,
        func: Literal["from_decorator"] = "from_decorator",
        *,
        scope: BaseScope | Literal["infer"] = "infer",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
        auto_open_scope: bool = True,
    ) -> Callable[[InjectableF], InjectableF]: ...

    def inject(
        self,
        func: InjectableF | Literal["from_decorator"] = "from_decorator",
        *,
        scope: BaseScope | Literal["infer"] = "infer",
        autoregister_dependencies: bool | Literal["from_container"] = "from_container",
        auto_open_scope: bool = True,
    ) -> InjectableF | Callable[[InjectableF], InjectableF]:
        resolved_scope = self._resolve_inject_scope(scope)
        resolved_autoregister_dependencies = self._resolve_inject_autoregister_dependencies(
            autoregister_dependencies=autoregister_dependencies,
        )

        def decorator(callable_obj: InjectableF) -> InjectableF:
            self._validate_injected_callable_signature(callable_obj)
            inspected_callable = self._injected_callable_inspector.inspect_callable(callable_obj)
            cache: dict[Container, Callable[..., Any]] = {}
            wrapper_config = _InjectWrapperConfig(
                callable_obj=callable_obj,
                scope=resolved_scope,
                autoregister_dependencies=resolved_autoregister_dependencies,
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

    def _resolve_inject_autoregister_dependencies(
        self,
        *,
        autoregister_dependencies: bool | Literal["from_container"],
    ) -> bool | None:
        autoregister_dependencies_value = cast("Any", autoregister_dependencies)
        if autoregister_dependencies_value == "from_container":
            return None
        if isinstance(autoregister_dependencies_value, bool):
            return autoregister_dependencies_value
        msg = "inject() parameter 'autoregister_dependencies' must be bool or 'from_container'."
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
            fallback_container.compile()
            return _InjectInvocationState(source="fallback", context_resolver=None)

        msg = (
            "Provider is not set for provider_context.inject. Pass "
            f"'{INJECT_RESOLVER_KWARG}' explicitly, enter a resolver context, "
            "or initialize a container with this ProviderContext."
        )
        raise DIWireProviderNotSetError(msg)

    def _require_inject_fallback_container(self) -> Container:
        fallback_container = self._fallback_container
        if fallback_container is None:
            msg = (
                "ProviderContext.inject requires a fallback container. Initialize a container "
                "with this ProviderContext before decorating callables."
            )
            raise DIWireProviderNotSetError(msg)
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
            autoregister_dependencies=wrapper_config.autoregister_dependencies,
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


provider_context = ProviderContext()
