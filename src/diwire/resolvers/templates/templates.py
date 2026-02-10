from textwrap import dedent

MODULE_TEMPLATE = dedent(
    """
    {{ module_docstring_block }}

    {{ imports_block }}

    {{ globals_block }}

    {{ classes_block }}

    {{ build_block }}
    """,
).strip()

IMPORTS_TEMPLATE = dedent(
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
    from diwire.providers import ProvidersRegistrations
    """,
).strip()

GLOBALS_TEMPLATE = dedent(
    """
    _MISSING_RESOLVER: Any = object()
    _MISSING_CACHE: Any = object()
    _MISSING_PROVIDER: Any = object()

    {{ provider_globals_block }}
    {% if lock_globals_block %}

    {{ lock_globals_block }}
    {% endif %}
    """,
).strip()

CLASS_TEMPLATE = dedent(
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

    {{ enter_method_block }}

    {{ exit_method_block }}

    {{ aenter_method_block }}

    {{ aexit_method_block }}
    {% if resolver_methods_block %}

    {{ resolver_methods_block }}
    {% endif %}
    """,
).strip()

INIT_METHOD_TEMPLATE = dedent(
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

ENTER_SCOPE_METHOD_TEMPLATE = dedent(
    """
    def enter_scope(self, scope: Any | None = None) -> {{ return_annotation }}:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

DISPATCH_RESOLVE_METHOD_TEMPLATE = dedent(
    """
    def resolve(self, dependency: Any) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

DISPATCH_ARESOLVE_METHOD_TEMPLATE = dedent(
    """
    async def aresolve(self, dependency: Any) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

CONTEXT_ENTER_METHOD_TEMPLATE = dedent(
    """
    def __enter__(self) -> {{ return_annotation }}:
        return self
    """,
).strip()

CONTEXT_AENTER_METHOD_TEMPLATE = dedent(
    """
    async def __aenter__(self) -> {{ return_annotation }}:
        return self
    """,
).strip()

CONTEXT_EXIT_NO_CLEANUP_TEMPLATE = dedent(
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

CONTEXT_AEXIT_NO_CLEANUP_TEMPLATE = dedent(
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

CONTEXT_EXIT_WITH_CLEANUP_TEMPLATE = dedent(
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
        if exc_type is None and cleanup_error is not None:
            raise cleanup_error
        return None
    """,
).strip()

CONTEXT_AEXIT_WITH_CLEANUP_TEMPLATE = dedent(
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
        if exc_type is None and cleanup_error is not None:
            raise cleanup_error
        return None
    """,
).strip()

SYNC_METHOD_TEMPLATE = dedent(
    """
    def resolve_{{ slot }}(self) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

ASYNC_METHOD_TEMPLATE = dedent(
    """
    async def aresolve_{{ slot }}(self) -> Any:
    {% if docstring_block %}
    {{ docstring_block }}
    {% endif %}
    {{ body_block }}
    """,
).strip()

BUILD_FUNCTION_TEMPLATE = dedent(
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
