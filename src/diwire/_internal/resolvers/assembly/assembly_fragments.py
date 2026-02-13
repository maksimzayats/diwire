from textwrap import dedent

MODULE_ASSEMBLY_FRAGMENT = dedent(
    """
    {{ module_docstring_block }}

    {{ imports_block }}

    {{ globals_block }}

    {{ classes_block }}

    {{ build_block }}
    """,
).strip()

IMPORTS_ASSEMBLY_FRAGMENT = dedent(
    """
    from __future__ import annotations
    {% if uses_asyncio_import %}
    import asyncio
    {% endif %}
    {% if uses_threading_import %}
    import threading
    {% endif %}
    {% if uses_generator_context_helpers %}
    from contextlib import asynccontextmanager, contextmanager
    {% endif %}
    from types import TracebackType
    from typing import Any, NoReturn

    from diwire.exceptions import (
        DIWireAsyncDependencyInSyncContextError,
        DIWireDependencyNotRegisteredError,
        DIWireScopeMismatchError,
    )
    from diwire._internal.markers import (
        is_async_provider_annotation,
        is_all_annotation,
        component_base_key,
        is_from_context_annotation,
        is_maybe_annotation,
        is_provider_annotation,
        strip_all_annotation,
        strip_from_context_annotation,
        strip_maybe_annotation,
        strip_provider_annotation,
    )
    from diwire._internal.providers import ProvidersRegistrations
    """,
).strip()

GLOBALS_ASSEMBLY_FRAGMENT = dedent(
    """
_MISSING_RESOLVER: Any = object()
_MISSING_CACHE: Any = object()
_MISSING_PROVIDER: Any = object()
_all_slots_by_key: dict[Any, tuple[int, ...]] = {}
_dep_registered_keys: set[Any] = set()

{{ provider_globals_block }}
{% if lock_globals_block %}

{{ lock_globals_block }}
{% endif %}
""",
).strip()

CLASS_ASSEMBLY_FRAGMENT = dedent(
    """
    class {{ class_name }}:
    {% if class_docstring_block %}
    {{ class_docstring_block }}

    {% endif %}
    {% if slots_block %}
    {{ slots_block }}

    {% endif %}
    {{ init_method_block }}

    {{ enter_scope_method_block }}

    {{ resolve_method_block }}

    {{ aresolve_method_block }}

    {{ resolve_from_context_method_block }}

    {{ is_registered_dependency_method_block }}

    {{ enter_method_block }}

    {{ exit_method_block }}

    {{ close_method_block }}

    {{ aenter_method_block }}

    {{ aexit_method_block }}

    {{ aclose_method_block }}
    {% if resolver_methods_block %}

    {{ resolver_methods_block }}
    {% endif %}
    """,
).strip()

INIT_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    def __init__(
        self,
    {{ signature_block }}
    ) -> None:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

ENTER_SCOPE_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    def enter_scope(
        self,
        scope: Any | None = None,
        *,
        context: Any | None = None,
    ) -> {{ return_annotation }}:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

DISPATCH_RESOLVE_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    def resolve(self, dependency: Any) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

DISPATCH_ARESOLVE_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    async def aresolve(self, dependency: Any) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

CONTEXT_ENTER_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    def __enter__(self) -> {{ return_annotation }}:
        return self
    """,
).strip()

CONTEXT_AENTER_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    async def __aenter__(self) -> {{ return_annotation }}:
        return self
    """,
).strip()

CONTEXT_CLOSE_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return self.__exit__(exc_type, exc_value, traceback)
    """,
).strip()

CONTEXT_ACLOSE_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    async def aclose(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return await self.__aexit__(exc_type, exc_value, traceback)
    """,
).strip()

CONTEXT_EXIT_NO_CLEANUP_ASSEMBLY_FRAGMENT = dedent(
    """
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None
    """,
).strip()

CONTEXT_AEXIT_NO_CLEANUP_ASSEMBLY_FRAGMENT = dedent(
    """
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None
    """,
).strip()

CONTEXT_EXIT_WITH_CLEANUP_ASSEMBLY_FRAGMENT = dedent(
    """
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        cleanup_error: BaseException | None = None
        while self._cleanup_callbacks:
            cleanup_kind, cleanup = self._cleanup_callbacks.pop()
            try:
                if cleanup_kind == 0:
                    cleanup(exc_type, exc_value, traceback)
                else:
                    msg = "Cannot execute async cleanup in sync context. Use 'async with'."
                    raise DIWireAsyncDependencyInSyncContextError(msg)
            except BaseException as error:
                if exc_type is None and cleanup_error is None:
                    cleanup_error = error
        if self._owned_scope_resolvers:
            for owned_scope_resolver in reversed(self._owned_scope_resolvers):
                try:
                    owned_scope_resolver.__exit__(exc_type, exc_value, traceback)
                except BaseException as error:
                    if exc_type is None and cleanup_error is None:
                        cleanup_error = error
        if exc_type is None and cleanup_error is not None:
            raise cleanup_error
        return None
    """,
).strip()

CONTEXT_AEXIT_WITH_CLEANUP_ASSEMBLY_FRAGMENT = dedent(
    """
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        cleanup_error: BaseException | None = None
        while self._cleanup_callbacks:
            cleanup_kind, cleanup = self._cleanup_callbacks.pop()
            try:
                if cleanup_kind == 0:
                    cleanup(exc_type, exc_value, traceback)
                else:
                    await cleanup(exc_type, exc_value, traceback)
            except BaseException as error:
                if exc_type is None and cleanup_error is None:
                    cleanup_error = error
        if self._owned_scope_resolvers:
            for owned_scope_resolver in reversed(self._owned_scope_resolvers):
                try:
                    await owned_scope_resolver.__aexit__(exc_type, exc_value, traceback)
                except BaseException as error:
                    if exc_type is None and cleanup_error is None:
                        cleanup_error = error
        if exc_type is None and cleanup_error is not None:
            raise cleanup_error
        return None
    """,
).strip()

SYNC_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    def resolve_{{ slot }}(self) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

ASYNC_METHOD_ASSEMBLY_FRAGMENT = dedent(
    """
    async def aresolve_{{ slot }}(self) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

BUILD_FUNCTION_ASSEMBLY_FRAGMENT = dedent(
    """
    def build_root_resolver(
        registrations: ProvidersRegistrations,
        *,
        cleanup_enabled: bool = True,
    ) -> {{ return_annotation }}:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()
