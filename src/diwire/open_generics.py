from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Iterable, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, NoReturn, TypeVar, cast, get_args, get_origin

from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireScopeMismatchError,
)
from diwire.injection import INJECT_RESOLVER_KWARG, INJECT_WRAPPER_MARKER
from diwire.lock_mode import LockMode
from diwire.providers import (
    ContextManagerProvider,
    FactoryProvider,
    GeneratorProvider,
    Lifetime,
    ProviderDependency,
    UserProviderObject,
)
from diwire.resolvers.protocol import ResolverProtocol
from diwire.scope import BaseScope

if TYPE_CHECKING:
    from typing_extensions import Self


OpenProviderKind = Literal["concrete_type", "factory", "generator", "context_manager"]
OpenBindingKind = Literal["dependency", "generic_argument", "generic_argument_type"]
_MISSING_CACHE = object()


@dataclass(frozen=True, slots=True)
class _OpenGenericBindingPlan:
    dependency: ProviderDependency
    kind: OpenBindingKind
    template: Any
    typevar: TypeVar | None = None


@dataclass(frozen=True, slots=True)
class _OpenGenericSpec:
    canonical_key: Any
    provider_kind: OpenProviderKind
    provider: UserProviderObject
    lifetime: Lifetime
    scope: BaseScope
    lock_mode: LockMode | Literal["auto"]
    is_async: bool
    is_any_dependency_async: bool
    needs_cleanup: bool
    bindings: tuple[_OpenGenericBindingPlan, ...]
    registration_order: int
    provider_is_inject_wrapper: bool

    @property
    def requires_async(self) -> bool:
        return self.is_async or self.is_any_dependency_async


@dataclass(frozen=True, slots=True)
class _OpenGenericMatch:
    spec: _OpenGenericSpec
    typevar_map: dict[TypeVar, Any]
    specificity: int


def canonicalize_open_key(dependency: Any) -> Any | None:
    """Normalize a dependency key into an open-generic registration key.

    Use this helper when registering providers for open generics. It returns a
    canonical representation that preserves TypeVar structure so matching can be
    performed against closed generic resolution requests.

    Args:
        dependency: Candidate registration key.

    Returns:
        A normalized open-generic key when ``dependency`` contains TypeVars, or
        ``None`` when the key is not open-generic.

    """
    origin = get_origin(dependency)
    if origin is None:
        parameters = tuple(
            parameter
            for parameter in getattr(dependency, "__parameters__", ())
            if isinstance(parameter, TypeVar)
        )
        if not parameters:
            return None
        return _rebuild_alias(origin=dependency, args=parameters, fallback=dependency)

    args = get_args(dependency)
    if not args:
        return None
    normalized_args = tuple(_normalize_generic_node(argument) for argument in args)
    normalized = _rebuild_alias(origin=origin, args=normalized_args, fallback=dependency)
    if contains_typevar(normalized):
        return normalized
    return None


def contains_typevar(value: Any) -> bool:
    """Return whether a type expression still contains a ``TypeVar``.

    Args:
        value: Type expression or object to inspect.

    Returns:
        ``True`` when any nested node contains a TypeVar, else ``False``.

    """
    if isinstance(value, TypeVar):
        return True

    origin = get_origin(value)
    if origin is not None:
        return any(contains_typevar(argument) for argument in get_args(value))

    parameters = getattr(value, "__parameters__", ())
    return any(isinstance(parameter, TypeVar) for parameter in parameters)


def substitute_typevars(value: Any, *, mapping: Mapping[TypeVar, Any]) -> Any:
    """Substitute TypeVars in a type expression using a resolved mapping.

    This is used during open-generic resolution to derive closed dependency keys
    from templates declared in provider dependencies.

    Args:
        value: Type expression template that may contain TypeVars.
        mapping: Mapping from template TypeVars to concrete type arguments.

    Returns:
        The substituted type expression with available TypeVars replaced.

    """
    if isinstance(value, TypeVar):
        return mapping.get(value, value)

    origin = get_origin(value)
    if origin is None:
        return value

    arguments = get_args(value)
    if not arguments:
        return value

    substituted_arguments = tuple(
        substitute_typevars(argument, mapping=mapping) for argument in arguments
    )
    return _rebuild_alias(origin=origin, args=substituted_arguments, fallback=value)


def validate_typevar_arguments(typevar_map: Mapping[TypeVar, Any]) -> None:
    """Validate closed generic arguments against TypeVar constraints and bounds.

    Args:
        typevar_map: Mapping from open TypeVars to candidate concrete arguments.

    Raises:
        DIWireInvalidGenericTypeArgumentError: If any argument violates TypeVar
            constraints or bound requirements.

    """
    for typevar, argument in typevar_map.items():
        if not _is_type_argument_valid(typevar=typevar, argument=argument):
            constraints = getattr(typevar, "__constraints__", ())
            bound = getattr(typevar, "__bound__", None)
            if constraints:
                formatted_constraints = ", ".join(repr(item) for item in constraints)
                msg = (
                    f"Generic argument {argument!r} for TypeVar '{typevar.__name__}' must satisfy "
                    f"one of: {formatted_constraints}."
                )
            elif bound is not None:
                msg = (
                    f"Generic argument {argument!r} for TypeVar '{typevar.__name__}' must satisfy "
                    f"bound {bound!r}."
                )
            else:
                msg = f"Generic argument {argument!r} is invalid for TypeVar '{typevar.__name__}'."
            raise DIWireInvalidGenericTypeArgumentError(msg)


class _OpenGenericRegistry:
    def __init__(self) -> None:
        self._specs_by_key: dict[Any, _OpenGenericSpec] = {}
        self._registration_counter = 0

    @dataclass(frozen=True, slots=True)
    class Snapshot:
        """A rollback snapshot for open generic registrations."""

        specs_by_key: dict[Any, _OpenGenericSpec]
        registration_counter: int

    def snapshot(self) -> Snapshot:
        """Capture current registry state for rollback."""
        return self.Snapshot(
            specs_by_key=dict(self._specs_by_key),
            registration_counter=self._registration_counter,
        )

    def restore(self, snapshot: Snapshot) -> None:
        """Restore registry state from a previous snapshot."""
        self._specs_by_key = dict(snapshot.specs_by_key)
        self._registration_counter = snapshot.registration_counter

    def has_specs(self) -> bool:
        return bool(self._specs_by_key)

    def values(self) -> tuple[_OpenGenericSpec, ...]:
        return tuple(self._specs_by_key.values())

    def register(  # noqa: PLR0913
        self,
        *,
        provides: Any,
        provider_kind: OpenProviderKind,
        provider: UserProviderObject,
        lifetime: Lifetime,
        scope: BaseScope,
        lock_mode: LockMode | Literal["auto"],
        is_async: bool,
        is_any_dependency_async: bool,
        needs_cleanup: bool,
        dependencies: list[ProviderDependency],
    ) -> _OpenGenericSpec | None:
        canonical_key = canonicalize_open_key(provides)
        if canonical_key is None:
            return None

        template_typevars = _collect_typevars(canonical_key)
        bindings = tuple(
            _build_binding_plan(
                dependency=dependency,
                template_typevars=template_typevars,
            )
            for dependency in dependencies
        )

        self._registration_counter += 1
        spec = _OpenGenericSpec(
            canonical_key=canonical_key,
            provider_kind=provider_kind,
            provider=provider,
            lifetime=lifetime,
            scope=scope,
            lock_mode=lock_mode,
            is_async=is_async,
            is_any_dependency_async=is_any_dependency_async,
            needs_cleanup=needs_cleanup,
            bindings=bindings,
            registration_order=self._registration_counter,
            provider_is_inject_wrapper=bool(getattr(provider, INJECT_WRAPPER_MARKER, False)),
        )
        self._specs_by_key[canonical_key] = spec
        return spec

    def find_best_match(self, dependency: Any) -> _OpenGenericMatch | None:
        if not _is_closed_generic_dependency(dependency):
            return None

        matches: list[_OpenGenericMatch] = []
        validation_error: DIWireInvalidGenericTypeArgumentError | None = None
        for spec in self._specs_by_key.values():
            typevar_map = _match_typevars(template=spec.canonical_key, concrete=dependency)
            if typevar_map is None:
                continue

            try:
                validate_typevar_arguments(typevar_map)
            except DIWireInvalidGenericTypeArgumentError as error:
                if validation_error is None:
                    validation_error = error
                continue

            matches.append(
                _OpenGenericMatch(
                    spec=spec,
                    typevar_map=typevar_map,
                    specificity=_specificity_score(spec.canonical_key),
                ),
            )

        if matches:
            return max(
                matches,
                key=lambda item: (item.specificity, item.spec.registration_order),
            )

        if validation_error is not None:
            raise validation_error
        return None

    def has_match_for_dependency(self, dependency: Any) -> bool:
        return self.find_best_match(dependency) is not None


class _OpenGenericResolver:  # pragma: no cover
    def __init__(  # noqa: PLR0913
        self,
        *,
        base_resolver: ResolverProtocol,
        registry: _OpenGenericRegistry,
        root_scope: BaseScope,
        has_async_specs: bool,
        scope_level: int,
        root_wrapper: _OpenGenericResolver | None = None,
        parent_wrapper: _OpenGenericResolver | None = None,
    ) -> None:
        self._base_resolver = base_resolver
        self._registry = registry
        self._root_scope = root_scope
        self._has_async_specs = has_async_specs
        self._scope_level = scope_level
        self._root_wrapper = self if root_wrapper is None else root_wrapper
        self._parent_wrapper = parent_wrapper
        self._cache: dict[Any, Any] = {}
        self._thread_locks: dict[Any, threading.Lock] = {}
        self._async_locks: dict[Any, asyncio.Lock] = {}
        self._cleanup_callbacks: list[tuple[int, Any]] = []
        self._cleanup_enabled = bool(
            getattr(base_resolver, "_cleanup_enabled", True),
        )
        self._owned_scope_wrappers: tuple[_OpenGenericResolver, ...] = ()

    def resolve(self, dependency: Any) -> Any:
        try:
            return self._base_resolver.resolve(dependency)
        except DIWireDependencyNotRegisteredError:
            open_match = self._registry.find_best_match(dependency)
            if open_match is None:
                raise
            return self._resolve_open_match_sync(
                dependency=dependency,
                match=open_match,
            )

    async def aresolve(self, dependency: Any) -> Any:
        try:
            return await self._base_resolver.aresolve(dependency)
        except DIWireDependencyNotRegisteredError:
            open_match = self._registry.find_best_match(dependency)
            if open_match is None:
                raise
            return await self._resolve_open_match_async(
                dependency=dependency,
                match=open_match,
            )

    def enter_scope(
        self,
        scope: BaseScope | None = None,
        *,
        context: Mapping[Any, Any] | None = None,
    ) -> _OpenGenericResolver:
        transition_path = _resolve_scope_transition_path(
            root_scope=self._root_scope,
            current_scope_level=self._scope_level,
            scope=scope,
        )
        if not transition_path:
            return self

        current_wrapper = self
        current_base_resolver = self._base_resolver
        created_wrappers: list[_OpenGenericResolver] = []

        for index, next_scope in enumerate(transition_path):
            if index == len(transition_path) - 1:
                current_base_resolver = current_base_resolver.enter_scope(
                    next_scope,
                    context=context,
                )
            else:
                current_base_resolver = current_base_resolver.enter_scope(next_scope)
            current_wrapper = _OpenGenericResolver(
                base_resolver=current_base_resolver,
                registry=self._registry,
                root_scope=self._root_scope,
                has_async_specs=self._has_async_specs,
                scope_level=next_scope.level,
                root_wrapper=self._root_wrapper,
                parent_wrapper=current_wrapper,
            )
            created_wrappers.append(current_wrapper)

        if len(created_wrappers) > 1:
            current_wrapper._owned_scope_wrappers = tuple(created_wrappers[:-1])
        return current_wrapper

    def __enter__(self) -> Self:
        self._base_resolver.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        callbacks: list[tuple[int, Any]] = (
            self._cleanup_callbacks if self._resolver_cleanup_callbacks() is None else []
        )

        def _base_exit_callback(
            callback_exc_type: type[BaseException] | None,
            callback_exc_value: BaseException | None,
            callback_traceback: TracebackType | None,
        ) -> None:
            self._base_resolver.__exit__(
                callback_exc_type,
                callback_exc_value,
                callback_traceback,
            )

        if self._owned_scope_wrappers:
            callbacks[:0] = [
                (
                    0,
                    lambda callback_exc_type, callback_exc_value, callback_traceback, owned_scope_wrapper=owned_scope_wrapper: (
                        owned_scope_wrapper.__exit__(
                            callback_exc_type,
                            callback_exc_value,
                            callback_traceback,
                        )
                    ),
                )
                for owned_scope_wrapper in self._owned_scope_wrappers
            ]

        callbacks.append((0, _base_exit_callback))
        _execute_sync_cleanup_callbacks(
            callbacks=callbacks,
            exc_type=exc_type,
            exc_value=exc_value,
            traceback=traceback,
        )

    async def __aenter__(self) -> Self:
        enter_result = self._base_resolver.__aenter__()
        if inspect.isawaitable(enter_result):
            await enter_result
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        callbacks: list[tuple[int, Any]] = (
            self._cleanup_callbacks if self._resolver_cleanup_callbacks() is None else []
        )

        async def _base_aexit_callback(
            callback_exc_type: type[BaseException] | None,
            callback_exc_value: BaseException | None,
            callback_traceback: TracebackType | None,
        ) -> None:
            await self._base_resolver.__aexit__(
                callback_exc_type,
                callback_exc_value,
                callback_traceback,
            )

        if self._owned_scope_wrappers:
            callbacks[:0] = [
                (
                    1,
                    lambda callback_exc_type, callback_exc_value, callback_traceback, owned_scope_wrapper=owned_scope_wrapper: (
                        owned_scope_wrapper.__aexit__(
                            callback_exc_type,
                            callback_exc_value,
                            callback_traceback,
                        )
                    ),
                )
                for owned_scope_wrapper in self._owned_scope_wrappers
            ]

        callbacks.append((1, _base_aexit_callback))
        await _execute_async_cleanup_callbacks(
            callbacks=callbacks,
            exc_type=exc_type,
            exc_value=exc_value,
            traceback=traceback,
        )

    def _resolve_open_match_sync(
        self,
        *,
        dependency: Any,
        match: _OpenGenericMatch,
    ) -> Any:
        if match.spec.requires_async:
            msg = f"Dependency {dependency!r} requires asynchronous resolution."
            raise DIWireAsyncDependencyInSyncContextError(msg)

        execution_owner = self._resolve_execution_owner(match.spec)
        cache_owner = self._resolve_cache_owner(match.spec)
        if cache_owner is not None:
            cached_value = cache_owner.get_cached(dependency)
            if cached_value is not _MISSING_CACHE:
                return cached_value

            if self._uses_thread_lock(match.spec):
                lock = cache_owner.get_thread_lock(dependency)
                with lock:
                    cached_value = cache_owner.get_cached(dependency)
                    if cached_value is not _MISSING_CACHE:
                        return cached_value
                    value = execution_owner.build_open_value_sync(match=match)
                    cache_owner.set_cached(dependency=dependency, value=value)
                    return value

            value = execution_owner.build_open_value_sync(match=match)
            cache_owner.set_cached(dependency=dependency, value=value)
            return value

        return execution_owner.build_open_value_sync(match=match)

    async def _resolve_open_match_async(
        self,
        *,
        dependency: Any,
        match: _OpenGenericMatch,
    ) -> Any:
        execution_owner = self._resolve_execution_owner(match.spec)
        cache_owner = self._resolve_cache_owner(match.spec)
        if cache_owner is not None:
            cached_value = cache_owner.get_cached(dependency)
            if cached_value is not _MISSING_CACHE:
                return cached_value

            if self._uses_async_lock(match.spec):
                lock = cache_owner.get_async_lock(dependency)
                async with lock:
                    cached_value = cache_owner.get_cached(dependency)
                    if cached_value is not _MISSING_CACHE:
                        return cached_value
                    value = await execution_owner.build_open_value_async(match=match)
                    cache_owner.set_cached(dependency=dependency, value=value)
                    return value

            value = await execution_owner.build_open_value_async(match=match)
            cache_owner.set_cached(dependency=dependency, value=value)
            return value

        return await execution_owner.build_open_value_async(match=match)

    @property
    def scope_level(self) -> int:
        return self._scope_level

    @property
    def parent_wrapper(self) -> _OpenGenericResolver | None:
        return self._parent_wrapper

    def get_cached(self, dependency: Any) -> Any:
        return self._cache.get(dependency, _MISSING_CACHE)

    def set_cached(self, *, dependency: Any, value: Any) -> None:
        self._cache[dependency] = value

    def get_thread_lock(self, dependency: Any) -> threading.Lock:
        return self._thread_locks.setdefault(dependency, threading.Lock())

    def get_async_lock(self, dependency: Any) -> asyncio.Lock:
        return self._async_locks.setdefault(dependency, asyncio.Lock())

    def build_open_value_sync(self, *, match: _OpenGenericMatch) -> Any:
        return self._build_open_value_sync(match=match)

    async def build_open_value_async(self, *, match: _OpenGenericMatch) -> Any:
        return await self._build_open_value_async(match=match)

    def _build_open_value_sync(self, *, match: _OpenGenericMatch) -> Any:
        call_arguments = self._resolve_call_arguments_sync(match=match)
        if match.spec.provider_kind == "concrete_type":
            concrete_type = _as_provider_type(match.spec.provider)
            return concrete_type(*call_arguments.args, **call_arguments.kwargs)
        if match.spec.provider_kind == "factory":
            factory = _as_factory_provider(match.spec.provider)
            return factory(*call_arguments.args, **call_arguments.kwargs)
        if match.spec.provider_kind == "generator":
            generator = _as_generator_provider(match.spec.provider)
            return self._build_generator_sync(generator=generator, call_arguments=call_arguments)
        context_manager_provider = _as_context_manager_provider(match.spec.provider)
        return self._build_context_manager_sync(
            context_manager_provider=context_manager_provider,
            call_arguments=call_arguments,
        )

    async def _build_open_value_async(self, *, match: _OpenGenericMatch) -> Any:
        call_arguments = await self._resolve_call_arguments_async(match=match)
        if match.spec.provider_kind == "concrete_type":
            concrete_type = _as_provider_type(match.spec.provider)
            return concrete_type(*call_arguments.args, **call_arguments.kwargs)
        if match.spec.provider_kind == "factory":
            factory = _as_factory_provider(match.spec.provider)
            result = factory(*call_arguments.args, **call_arguments.kwargs)
            if match.spec.is_async:
                return await result
            return result
        if match.spec.provider_kind == "generator":
            generator = _as_generator_provider(match.spec.provider)
            return await self._build_generator_async(
                generator=generator,
                call_arguments=call_arguments,
                provider_is_async=match.spec.is_async,
            )
        context_manager_provider = _as_context_manager_provider(match.spec.provider)
        return await self._build_context_manager_async(
            context_manager_provider=context_manager_provider,
            call_arguments=call_arguments,
            provider_is_async=match.spec.is_async,
        )

    def _resolve_call_arguments_sync(self, *, match: _OpenGenericMatch) -> _CallArguments:
        positional_arguments: list[Any] = []
        keyword_arguments: dict[str, Any] = {}
        for binding in match.spec.bindings:
            value = self._resolve_binding_value_sync(
                binding=binding,
                typevar_map=match.typevar_map,
            )
            _append_call_argument(
                dependency=binding.dependency,
                value=value,
                positional_arguments=positional_arguments,
                keyword_arguments=keyword_arguments,
            )
        if match.spec.provider_is_inject_wrapper:
            keyword_arguments[INJECT_RESOLVER_KWARG] = self
        return _CallArguments(
            args=tuple(positional_arguments),
            kwargs=keyword_arguments,
        )

    async def _resolve_call_arguments_async(self, *, match: _OpenGenericMatch) -> _CallArguments:
        positional_arguments: list[Any] = []
        keyword_arguments: dict[str, Any] = {}
        for binding in match.spec.bindings:
            value = await self._resolve_binding_value_async(
                binding=binding,
                typevar_map=match.typevar_map,
            )
            _append_call_argument(
                dependency=binding.dependency,
                value=value,
                positional_arguments=positional_arguments,
                keyword_arguments=keyword_arguments,
            )
        if match.spec.provider_is_inject_wrapper:
            keyword_arguments[INJECT_RESOLVER_KWARG] = self
        return _CallArguments(
            args=tuple(positional_arguments),
            kwargs=keyword_arguments,
        )

    def _resolve_binding_value_sync(
        self,
        *,
        binding: _OpenGenericBindingPlan,
        typevar_map: Mapping[TypeVar, Any],
    ) -> Any:
        if binding.kind in {"generic_argument", "generic_argument_type"}:
            if binding.typevar is None:
                msg = "Open generic binding requires a TypeVar."
                raise DIWireInvalidGenericTypeArgumentError(msg)
            return typevar_map[binding.typevar]

        resolved_dependency = substitute_typevars(binding.template, mapping=typevar_map)
        if contains_typevar(resolved_dependency):
            msg = (
                f"Open generic dependency template {binding.template!r} still contains "
                "unresolved TypeVars after substitution."
            )
            raise DIWireInvalidGenericTypeArgumentError(msg)
        return self.resolve(resolved_dependency)

    async def _resolve_binding_value_async(
        self,
        *,
        binding: _OpenGenericBindingPlan,
        typevar_map: Mapping[TypeVar, Any],
    ) -> Any:
        if binding.kind in {"generic_argument", "generic_argument_type"}:
            if binding.typevar is None:
                msg = "Open generic binding requires a TypeVar."
                raise DIWireInvalidGenericTypeArgumentError(msg)
            return typevar_map[binding.typevar]

        resolved_dependency = substitute_typevars(binding.template, mapping=typevar_map)
        if contains_typevar(resolved_dependency):
            msg = (
                f"Open generic dependency template {binding.template!r} still contains "
                "unresolved TypeVars after substitution."
            )
            raise DIWireInvalidGenericTypeArgumentError(msg)
        return await self.aresolve(resolved_dependency)

    def _build_generator_sync(
        self,
        *,
        generator: Any,
        call_arguments: _CallArguments,
    ) -> Any:
        if self._cleanup_enabled:
            context_manager = contextmanager(generator)(
                *call_arguments.args,
                **call_arguments.kwargs,
            )
            value = context_manager.__enter__()
            self._register_cleanup(kind=0, callback=context_manager.__exit__)
            return value
        provider_generator = generator(*call_arguments.args, **call_arguments.kwargs)
        return next(provider_generator)

    async def _build_generator_async(
        self,
        *,
        generator: Any,
        call_arguments: _CallArguments,
        provider_is_async: bool,
    ) -> Any:
        if provider_is_async:
            if self._cleanup_enabled:
                async_context_manager = asynccontextmanager(generator)(
                    *call_arguments.args,
                    **call_arguments.kwargs,
                )
                value = await async_context_manager.__aenter__()
                self._register_cleanup(kind=1, callback=async_context_manager.__aexit__)
                return value
            provider_generator = generator(*call_arguments.args, **call_arguments.kwargs)
            return await anext(provider_generator)

        if self._cleanup_enabled:
            sync_context_manager = contextmanager(generator)(
                *call_arguments.args,
                **call_arguments.kwargs,
            )
            value = sync_context_manager.__enter__()
            self._register_cleanup(kind=0, callback=sync_context_manager.__exit__)
            return value
        provider_generator = generator(*call_arguments.args, **call_arguments.kwargs)
        return next(provider_generator)

    def _build_context_manager_sync(
        self,
        *,
        context_manager_provider: Any,
        call_arguments: _CallArguments,
    ) -> Any:
        context_manager = context_manager_provider(*call_arguments.args, **call_arguments.kwargs)
        value = context_manager.__enter__()
        if self._cleanup_enabled:
            self._register_cleanup(kind=0, callback=context_manager.__exit__)
        return value

    async def _build_context_manager_async(
        self,
        *,
        context_manager_provider: Any,
        call_arguments: _CallArguments,
        provider_is_async: bool,
    ) -> Any:
        context_manager = context_manager_provider(*call_arguments.args, **call_arguments.kwargs)
        if provider_is_async:
            value = await context_manager.__aenter__()
            if self._cleanup_enabled:
                self._register_cleanup(kind=1, callback=context_manager.__aexit__)
            return value

        value = context_manager.__enter__()
        if self._cleanup_enabled:
            self._register_cleanup(kind=0, callback=context_manager.__exit__)
        return value

    def _register_cleanup(self, *, kind: Literal[0, 1], callback: Any) -> None:
        callbacks = self._resolver_cleanup_callbacks()
        if callbacks is not None:
            callbacks.append((kind, callback))
            return
        self._cleanup_callbacks.append((kind, callback))

    def _resolver_cleanup_callbacks(self) -> list[tuple[int, Any]] | None:
        callbacks = getattr(self._base_resolver, "_cleanup_callbacks", None)
        if isinstance(callbacks, list):
            return callbacks
        return None

    def _resolve_execution_owner(self, spec: _OpenGenericSpec) -> _OpenGenericResolver:
        provider_scope_owner = self._scope_owner_for_level(spec.scope.level)
        if provider_scope_owner is None:
            self._raise_scope_mismatch(spec.scope.level)

        cache_owner = self._resolve_cache_owner(spec)
        execution_owner = cache_owner if cache_owner is not None else provider_scope_owner
        if execution_owner.scope_level < spec.scope.level:
            self._raise_scope_mismatch(spec.scope.level)
        return execution_owner

    def _resolve_cache_owner(self, spec: _OpenGenericSpec) -> _OpenGenericResolver | None:
        if spec.lifetime is Lifetime.TRANSIENT:
            return None
        return self._scope_owner_for_level(spec.scope.level)

    def _scope_owner_for_level(self, scope_level: int) -> _OpenGenericResolver | None:
        if self._scope_level < scope_level:
            return None

        cursor: _OpenGenericResolver | None = self
        while cursor is not None:
            if cursor.scope_level == scope_level:
                return cursor
            cursor = cursor.parent_wrapper
        if self._root_wrapper.scope_level == scope_level:
            return self._root_wrapper
        return None

    def _uses_thread_lock(self, spec: _OpenGenericSpec) -> bool:
        if spec.requires_async:
            return False
        return self._effective_lock_mode(spec) is LockMode.THREAD

    def _uses_async_lock(self, spec: _OpenGenericSpec) -> bool:
        if not spec.requires_async:
            return False
        return self._effective_lock_mode(spec) is LockMode.ASYNC

    def _effective_lock_mode(self, spec: _OpenGenericSpec) -> LockMode:
        if spec.lock_mode == "auto":
            if self._has_async_specs:
                return LockMode.ASYNC
            return LockMode.THREAD
        return spec.lock_mode

    def _raise_scope_mismatch(self, required_scope_level: int) -> NoReturn:
        msg = f"Dependency requires opened scope level {required_scope_level}."
        raise DIWireScopeMismatchError(msg)


@dataclass(frozen=True, slots=True)
class _CallArguments:
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


def _append_call_argument(
    *,
    dependency: ProviderDependency,
    value: Any,
    positional_arguments: list[Any],
    keyword_arguments: dict[str, Any],
) -> None:
    kind = cast("Any", dependency.parameter.kind)
    if kind is inspect.Parameter.POSITIONAL_ONLY:
        positional_arguments.append(value)
        return
    if kind is inspect.Parameter.POSITIONAL_OR_KEYWORD:
        keyword_arguments[dependency.parameter.name] = value
        return
    if kind is inspect.Parameter.KEYWORD_ONLY:
        keyword_arguments[dependency.parameter.name] = value
        return
    if kind is inspect.Parameter.VAR_POSITIONAL:
        positional_arguments.extend(cast_iterable(value))
        return
    if kind is inspect.Parameter.VAR_KEYWORD:
        keyword_arguments.update(cast_mapping(value))
        return
    keyword_arguments[dependency.parameter.name] = value


def cast_iterable(value: Any) -> Iterable[Any]:
    """Validate and return an iterable variadic argument payload.

    Args:
        value: Value bound for a ``*args`` provider dependency.

    Returns:
        The input value cast as ``Iterable[Any]``.

    Raises:
        TypeError: If ``value`` is not iterable.

    """
    if isinstance(value, Iterable):
        return value
    msg = f"Expected iterable value for variadic positional dependency, got {value!r}."
    raise TypeError(msg)


def cast_mapping(value: Any) -> Mapping[str, Any]:
    """Validate and return a mapping variadic keyword payload.

    Args:
        value: Value bound for a ``**kwargs`` provider dependency.

    Returns:
        The input value cast as ``Mapping[str, Any]``.

    Raises:
        TypeError: If ``value`` is not a mapping.

    """
    if isinstance(value, Mapping):
        return value
    msg = f"Expected mapping value for variadic keyword dependency, got {value!r}."
    raise TypeError(msg)


def _build_binding_plan(
    *,
    dependency: ProviderDependency,
    template_typevars: tuple[TypeVar, ...],
) -> _OpenGenericBindingPlan:
    if isinstance(dependency.provides, TypeVar) and dependency.provides in template_typevars:
        return _OpenGenericBindingPlan(
            dependency=dependency,
            kind="generic_argument",
            template=dependency.provides,
            typevar=dependency.provides,
        )

    origin = get_origin(dependency.provides)
    origin_any = cast("Any", origin)
    arguments = get_args(dependency.provides)
    if (
        origin_any is type
        and len(arguments) == 1
        and isinstance(arguments[0], TypeVar)
        and arguments[0] in template_typevars
    ):
        return _OpenGenericBindingPlan(
            dependency=dependency,
            kind="generic_argument_type",
            template=dependency.provides,
            typevar=arguments[0],
        )

    return _OpenGenericBindingPlan(
        dependency=dependency,
        kind="dependency",
        template=dependency.provides,
    )


def _collect_typevars(value: Any) -> tuple[TypeVar, ...]:
    found: list[TypeVar] = []
    _collect_typevars_into(value=value, found=found)
    unique: dict[TypeVar, None] = {}
    for typevar in found:
        unique[typevar] = None
    return tuple(unique)


def _collect_typevars_into(*, value: Any, found: list[TypeVar]) -> None:
    if isinstance(value, TypeVar):
        found.append(value)
        return

    origin = get_origin(value)
    if origin is not None:
        for argument in get_args(value):
            _collect_typevars_into(value=argument, found=found)
        return

    found.extend(
        parameter
        for parameter in getattr(value, "__parameters__", ())
        if isinstance(parameter, TypeVar)
    )


def _match_typevars(*, template: Any, concrete: Any) -> dict[TypeVar, Any] | None:
    mapping: dict[TypeVar, Any] = {}
    if _match_node(template=template, concrete=concrete, mapping=mapping):
        return mapping
    return None


def _match_node(  # noqa: PLR0911
    *,
    template: Any,
    concrete: Any,
    mapping: dict[TypeVar, Any],
) -> bool:
    if isinstance(template, TypeVar):
        known = mapping.get(template)
        if known is None:
            mapping[template] = concrete
            return True
        return known == concrete

    template_origin = get_origin(template)
    if template_origin is None:
        template_open = canonicalize_open_key(template)
        if template_open is not None:
            return _match_node(template=template_open, concrete=concrete, mapping=mapping)
        return template == concrete

    concrete_origin = get_origin(concrete)
    if concrete_origin != template_origin:
        return False

    template_arguments = get_args(template)
    concrete_arguments = get_args(concrete)
    if len(template_arguments) != len(concrete_arguments):
        return False

    return all(
        _match_node(template=template_argument, concrete=concrete_argument, mapping=mapping)
        for template_argument, concrete_argument in zip(
            template_arguments,
            concrete_arguments,
            strict=True,
        )
    )


def _is_closed_generic_dependency(dependency: Any) -> bool:
    origin = get_origin(dependency)
    if origin is None:
        return False
    arguments = get_args(dependency)
    if not arguments:
        return False
    return not any(contains_typevar(argument) for argument in arguments)


def _specificity_score(value: Any) -> int:
    if isinstance(value, TypeVar):
        return 0

    origin = get_origin(value)
    if origin is None:
        return 2

    arguments = get_args(value)
    if not arguments:
        return 2
    return 1 + sum(_specificity_score(argument) for argument in arguments)


def _normalize_generic_node(value: Any) -> Any:
    if isinstance(value, TypeVar):
        return value

    origin = get_origin(value)
    if origin is not None:
        arguments = get_args(value)
        normalized_arguments = tuple(_normalize_generic_node(argument) for argument in arguments)
        return _rebuild_alias(origin=origin, args=normalized_arguments, fallback=value)

    parameters = tuple(
        parameter
        for parameter in getattr(value, "__parameters__", ())
        if isinstance(parameter, TypeVar)
    )
    if not parameters:
        return value
    normalized_parameters = tuple(_normalize_generic_node(parameter) for parameter in parameters)
    return _rebuild_alias(origin=value, args=normalized_parameters, fallback=value)


def _rebuild_alias(*, origin: Any, args: tuple[Any, ...], fallback: Any) -> Any:
    try:
        if len(args) == 1:
            return origin[args[0]]
        return origin[args]
    except TypeError:
        return fallback


def _is_type_argument_valid(*, typevar: TypeVar, argument: Any) -> bool:
    constraints = getattr(typevar, "__constraints__", ())
    if constraints:
        return any(
            _matches_type_constraint(argument=argument, constraint=constraint)
            for constraint in constraints
        )
    bound = getattr(typevar, "__bound__", None)
    if bound is None:
        return True
    return _matches_type_constraint(argument=argument, constraint=bound)


def _matches_type_constraint(*, argument: Any, constraint: Any) -> bool:
    if constraint is Any:
        return True
    argument_type = _origin_or_self(argument)
    constraint_type = _origin_or_self(constraint)
    if isinstance(argument_type, type) and isinstance(constraint_type, type):
        try:
            return issubclass(argument_type, constraint_type)
        except TypeError:
            return False
    return argument == constraint


def _origin_or_self(value: Any) -> Any:
    return get_origin(value) or value


def _resolve_scope_transition_path(
    *,
    root_scope: BaseScope,
    current_scope_level: int,
    scope: BaseScope | None,
) -> list[BaseScope]:
    managed_scopes = sorted(
        (candidate for candidate in root_scope.owner() if candidate.level >= root_scope.level),
        key=lambda candidate: candidate.level,
    )

    if scope is None:
        deeper_scopes = [
            candidate for candidate in managed_scopes if candidate.level > current_scope_level
        ]
        if not deeper_scopes:
            msg = f"Cannot enter deeper scope from level {current_scope_level}."
            raise DIWireScopeMismatchError(msg)
        immediate_next = deeper_scopes[0]
        default_next = next(
            (candidate for candidate in deeper_scopes if not candidate.skippable),
            immediate_next,
        )
        target_scope_level = default_next.level
    else:
        target_scope_level = scope.level
        if target_scope_level == current_scope_level:
            return []
    if target_scope_level <= current_scope_level:
        msg = f"Cannot enter scope level {target_scope_level} from level {current_scope_level}."
        raise DIWireScopeMismatchError(msg)

    valid_scope_levels = {candidate.level for candidate in managed_scopes}
    if target_scope_level not in valid_scope_levels:
        msg = (
            f"Scope level {target_scope_level} is not a valid next transition from "
            f"level {current_scope_level}."
        )
        raise DIWireScopeMismatchError(msg)

    transition_path: list[BaseScope] = []
    cursor_level = current_scope_level
    while cursor_level < target_scope_level:
        deeper_scopes = [
            candidate for candidate in managed_scopes if candidate.level > cursor_level
        ]
        immediate_next = deeper_scopes[0]
        default_next = next(
            (candidate for candidate in deeper_scopes if not candidate.skippable),
            immediate_next,
        )
        if immediate_next.level != target_scope_level and default_next.level <= target_scope_level:
            next_scope = default_next
        else:
            next_scope = immediate_next
        transition_path.append(next_scope)
        cursor_level = next_scope.level
    return transition_path


def _execute_sync_cleanup_callbacks(
    *,
    callbacks: list[tuple[int, Any]],
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
) -> None:
    cleanup_error: BaseException | None = None
    while callbacks:
        cleanup_kind, cleanup_callback = callbacks.pop()
        try:
            if cleanup_kind == 0:
                cleanup_callback(exc_type, exc_value, traceback)
            else:
                _raise_async_cleanup_in_sync_context()
        except Exception as error:  # noqa: BLE001
            if exc_type is None and cleanup_error is None:
                cleanup_error = error
    if exc_type is None and cleanup_error is not None:
        raise cleanup_error


async def _execute_async_cleanup_callbacks(
    *,
    callbacks: list[tuple[int, Any]],
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
) -> None:
    cleanup_error: BaseException | None = None
    while callbacks:
        cleanup_kind, cleanup_callback = callbacks.pop()
        try:
            if cleanup_kind == 0:
                cleanup_callback(exc_type, exc_value, traceback)
            else:
                await cleanup_callback(exc_type, exc_value, traceback)
        except Exception as error:  # noqa: BLE001
            if exc_type is None and cleanup_error is None:
                cleanup_error = error
    if exc_type is None and cleanup_error is not None:
        raise cleanup_error


def _as_provider_type(provider: UserProviderObject) -> type[Any]:
    if isinstance(provider, type):
        return provider
    msg = f"Expected concrete type provider, got {provider!r}."
    raise TypeError(msg)


def _as_factory_provider(provider: UserProviderObject) -> FactoryProvider[Any]:
    if callable(provider):
        return provider
    msg = f"Expected factory provider, got {provider!r}."
    raise TypeError(msg)


def _as_generator_provider(provider: UserProviderObject) -> GeneratorProvider[Any]:
    if callable(provider):
        return provider
    msg = f"Expected generator provider, got {provider!r}."
    raise TypeError(msg)


def _as_context_manager_provider(provider: UserProviderObject) -> ContextManagerProvider[Any]:
    if callable(provider):
        return provider
    msg = f"Expected context manager provider, got {provider!r}."
    raise TypeError(msg)


def _raise_async_cleanup_in_sync_context() -> None:
    msg = "Cannot execute async cleanup in sync context. Use 'async with'."
    raise DIWireAsyncDependencyInSyncContextError(msg)


OpenGenericRegistry = _OpenGenericRegistry
OpenGenericResolver = _OpenGenericResolver
