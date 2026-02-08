from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import (
    Any,
)

from diwire.container import BaseScope

_missing_resolver: Any = object()

_number_of_dependencies = 3


# spec: ProviderSpec(slot=1, provides=<class 'int'>, provider=42, provider_kind=<ProviderKind.VALUE: 1>, lifetime=<Lifetime.SINGLETON: 'singleton'>, scope=None, dependencies=[], variables=<__main__._SpecVariables object at 0x5c9b8588410>)
_dep_1_type: type[Any]
_dep_1_resolver: Any
_dep_1_threading_lock = threading.Lock()
_dep_1_asyncio_lock = asyncio.Lock()

# spec: ProviderSpec(slot=2, provides=<class 'float'>, provider=<function <lambda> at 0x5c9b9815400>, provider_kind=<ProviderKind.CALL: 2>, lifetime=<Lifetime.SINGLETON: 'singleton'>, scope=None, dependencies=[], variables=<__main__._SpecVariables object at 0x5c9b8596e10>)
_dep_2_type: type[Any]
_dep_2_resolver: Any
_dep_2_threading_lock = threading.Lock()
_dep_2_asyncio_lock = asyncio.Lock()

# spec: ProviderSpec(slot=3, provides=<class 'str'>, provider=<function <lambda> at 0x5c9b9815340>, provider_kind=<ProviderKind.CALL: 2>, lifetime=<Lifetime.SINGLETON: 'singleton'>, scope=<Scope.REQUEST: 3>, dependencies=[ProviderDependency(provides=<class 'float'>, parameter=<Parameter "f: float">)], variables=<__main__._SpecVariables object at 0x5c9b8597950>)
_dep_3_type: type[Any]
_dep_3_resolver: Any
_dep_3_threading_lock = threading.Lock()
_dep_3_asyncio_lock = asyncio.Lock()


class RootResolver:
    def enter_scope(self, scope: BaseScope):

        if scope == 1:
            return _AppResolver(root_resolver=self)

        if scope == 2:
            return _SessionResolver(root_resolver=self)

        if scope == 3:
            return _RequestResolver(root_resolver=self)

        raise ValueError(f"Unknown scope: {scope}")

    def resolve(self, dependency: Any) -> Any:
        return _resolvers_by_type_mapping[dependency](self)

    def resolve_1(self) -> Any:
        # after first resolution, we will set to lambda: instance
        # no need to check for attr, we will replace the resolver method
        with _dep_1_threading_lock:
            value = _dep_1_resolver()
            self.resolve_1 = lambda: value
            return value

    def resolve_2(self) -> Any:
        # after first resolution, we will set to lambda: instance
        # no need to check for attr, we will replace the resolver method
        with _dep_2_threading_lock:
            value = _dep_2_resolver()
            self.resolve_2 = lambda: value
            return value


# scope APP
# seen scopes: []


class _AppResolver:
    def __init__(
        self,
        root_resolver: RootResolver,
    ) -> None:
        self._opened_resources: list[Any] = []
        self._root_resolver = root_resolver

    def enter_scope(
        self,
        scope: BaseScope,
    ) -> Any:

        if scope == 2:
            return _SessionResolver(
                root_resolver=self._root_resolver,
                app_resolver=self,
            )

        if scope == 3:
            return _RequestResolver(
                root_resolver=self._root_resolver,
                app_resolver=self,
            )

        raise ValueError(f"Unknown scope: {scope}")

    def resolve(self, dependency: Any) -> Any:
        return _resolvers_by_type_mapping[dependency](self)


# scope SESSION
# seen scopes: [<Scope.APP: 1>]


class _SessionResolver:
    def __init__(
        self,
        root_resolver: RootResolver,
        app_resolver: _AppResolver = _missing_resolver,
    ) -> None:
        self._opened_resources: list[Any] = []
        self._root_resolver = root_resolver
        self._app_resolver = app_resolver

    def enter_scope(
        self,
        scope: BaseScope,
    ) -> Any:

        if scope == 3:
            return _RequestResolver(
                root_resolver=self._root_resolver,
                app_resolver=self._app_resolver,
                session_resolver=self,
            )

        raise ValueError(f"Unknown scope: {scope}")

    def resolve(self, dependency: Any) -> Any:
        return _resolvers_by_type_mapping[dependency](self)


# scope REQUEST
# seen scopes: [<Scope.APP: 1>, <Scope.SESSION: 2>]


class _RequestResolver:
    def __init__(
        self,
        root_resolver: RootResolver,
        app_resolver: _AppResolver = _missing_resolver,
        session_resolver: _SessionResolver = _missing_resolver,
    ) -> None:
        self._opened_resources: list[Any] = []
        self._root_resolver = root_resolver
        self._app_resolver = app_resolver
        self._session_resolver = session_resolver

    def resolve(self, dependency: Any) -> Any:
        return _resolvers_by_type_mapping[dependency](self)

    def resolve_3(self) -> Any:
        with _dep_3_threading_lock:
            value = _dep_3_resolver()
            self.resolve_3 = lambda: value
            return value


_resolvers_by_type_mapping: dict[type[Any], Callable[[Any], Any]] = {}

_resolvers_by_slot_mapping = {
    1: RootResolver.resolve_1,
    2: RootResolver.resolve_2,
    3: _RequestResolver.resolve_3,
}


def init(registrations) -> RootResolver:
    for slot, resolver in _resolvers_by_slot_mapping.items():
        registration = registrations.get_by_slot(slot)
        _resolvers_by_type_mapping[registration.dependency_type] = resolver

    return RootResolver()
