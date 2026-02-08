from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from enum import Enum, auto
from inspect import Parameter
from pathlib import Path
from typing import Any, Iterator, TypeAlias, get_type_hints

import jinja2

UserDependency: TypeAlias = type[Any]
"""A dependency that been registered or trying to be resolved from the user's code."""

UserProviderObject: TypeAlias = Any
BaseScope: TypeAlias = int


class ProviderKind(Enum):
    VALUE = auto()
    """
    A simple value, e.g., an integer, string, or object instance.
    Usage in provider: `return value`
    """

    CALL = auto()
    """
    A callable that returns a value when invoked. Could be a function or a class constructor.
    Usage in provider: `return callable(**dependencies)`
    """
    ASYNC_CALL = auto()
    """
    An asynchronous callable that returns a value when awaited.
    Usage in provider: `return await async_callable(**dependencies)`
    """

    GENERATOR = auto()
    """
    A generator callable that yields a value.
    Usage in provider:
    ```
    gen = generator_function(**dependencies)
    resource = next(gen)
    scope_context.open_resources.append(OpenGeneratorResource(gen))
    return resource
    ```
    """
    ASYNC_GENERATOR = auto()
    """
    An asynchronous generator callable that yields a value.
    Usage in provider:
    ```
    agen = async_generator_function(**dependencies)
    resource = await anext(agen)
    scope_context.open_resources.append(OpenAsyncGeneratorResource(agen))
    return resource
    ```
    """

    CONTEXT_MANAGER = auto()
    """
    A context manager callable that provides a resource within a `with` block.
    Usage in provider:
    ```
    context_manager = context_manager_function(**dependencies)
    resource = context_manager.__enter__()
    scope_context.open_resources.append(OpenContextManagerResource(context_manager))
    return resource
    ```
    """
    ASYNC_CONTEXT_MANAGER = auto()
    """
    An asynchronous context manager callable that provides a resource within an `async with` block.
    Usage in provider:
    ```
    async_context_manager = async_context_manager_function(**dependencies)
    resource = await async_context_manager.__aenter__()
    scope_context.open_resources.append(OpenAsyncContextManagerResource(async_context_manager))
    return resource
    ```
    """


class Lifetime(str, Enum):
    """Defines the lifetime of a service in the container."""

    TRANSIENT = "transient"
    """A new instance is created every time the service is requested."""

    SINGLETON = "singleton"
    """A single instance is created and shared for the lifetime of the container."""

    SCOPED = "scoped"
    """Instance is shared within a scope, different instances across scopes."""


class Scope(int, Enum):
    """A default pre-defined set of scopes."""

    APP = auto()
    SESSION = auto()
    REQUEST = auto()


@dataclass(slots=True)
class ProviderDependency:
    provides: UserDependency
    parameter: Parameter


@dataclass(kw_only=True)
class ProviderSpec:
    """A specification of a provider in the dependency injection system."""

    slot: int

    provides: UserDependency
    provider: UserProviderObject
    provider_kind: ProviderKind
    lifetime: Lifetime

    scope: BaseScope | None = None
    dependencies: list[ProviderDependency] = field(default_factory=list)

    variables: "_SpecVariables" = field(init=False)

    def __post_init__(self) -> None:
        self.variables = _SpecVariables(spec=self)


@dataclass(slots=True)
class _ProviderDependenciesExtractor:
    def extract_from_provider(
        self,
        provider: UserProviderObject,
    ) -> list[ProviderDependency]:
        if not isinstance(provider, type):
            # instance handling
            return []

        target_for_hints: Any = provider
        signature_target: Any = provider
        bound_names: set[str] = set()

        if isinstance(provider, functools.partial):
            target_for_hints = provider.func
            signature_target = provider
            bound = inspect.signature(provider.func).bind_partial(
                *provider.args,
                **(provider.keywords or {}),
            )
            bound_names = set(bound.arguments.keys())
        elif inspect.isclass(provider):
            target_for_hints = provider.__init__
            signature_target = provider
        elif (
            not inspect.isfunction(provider)
            and not inspect.ismethod(provider)
            and not inspect.isbuiltin(provider)
            and callable(provider)
        ):
            target_for_hints = provider.__call__
            signature_target = provider.__call__

        type_hints = get_type_hints(target_for_hints, include_extras=True)
        sig = inspect.signature(signature_target)
        dependencies: list[ProviderDependency] = []

        for dep_name, dep_type in type_hints.items():
            if dep_name == "return" or dep_name in bound_names:
                continue
            param = sig.parameters.get(dep_name)
            if param is None:
                continue
            dependencies.append(
                ProviderDependency(
                    provides=dep_type,
                    parameter=param,
                ),
            )

        return dependencies


@dataclass(slots=True)
class _ProviderSpecIntrospector:
    pass


@dataclass(slots=True)
class _ProviderSpecExtractor:
    # fmt: off
    _provider_dependencies_extractor: _ProviderDependenciesExtractor = field(default_factory=_ProviderDependenciesExtractor)
    _provider_spec_introspector: _ProviderSpecIntrospector = field(default_factory=_ProviderSpecIntrospector)
    # fmt: on

    _specs_extracted: int = 0

    def extract(
        self,
        *,
        provider: UserProviderObject | None = None,
        provider_kind: ProviderKind | None = None,
        provides: UserDependency | None = None,
        scope: Scope | None = None,
        lifetime: Lifetime | None = None,
        dependencies: list[ProviderDependency] | None = None,
    ) -> ProviderSpec:
        if provider is None and provides is None:
            raise ValueError("Either provider or provides must be specified")

        if provider is None:
            provider = self._extract_provider_from_provides(provides)
        elif provides is None:
            provides = self._extract_provides_from_provider(provider)

        if provider_kind is None:
            provider_kind = self._extract_provider_kind_from_provider(provider)

        if scope is None:
            scope = self._extract_scope_from_provider(provider)

        if lifetime is None:
            lifetime = self._extract_lifetime_from_provider(provider, scope=scope)

        if dependencies is None:
            dependencies = self._provider_dependencies_extractor.extract_from_provider(provider)

        self._specs_extracted += 1
        return ProviderSpec(
            slot=self._specs_extracted,
            provides=provides,
            provider=provider,
            provider_kind=provider_kind,
            lifetime=lifetime,
            scope=scope,
            dependencies=dependencies,
        )

    def _extract_provider_from_provides(self, provides: UserDependency) -> UserProviderObject:
        return provides

    def _extract_provides_from_provider(self, provider: UserProviderObject) -> UserDependency:
        if not isinstance(provider, type):
            # instance handling
            return type(provider)

        return provider

    def _extract_provider_kind_from_provider(self, provider: UserProviderObject) -> ProviderKind:
        if not isinstance(provider, type):
            # instance handling
            return ProviderKind.VALUE

        return ProviderKind.CALL

    def _extract_lifetime_from_provider(
        self,
        provider: UserProviderObject,
        scope: BaseScope | None = None,
    ) -> Lifetime | None:
        if not isinstance(provider, type):
            # instance handling
            return Lifetime.SINGLETON

        if scope is not None:
            return Lifetime.SCOPED

        raise ValueError("Cannot determine lifetime from provider")

    def _extract_scope_from_provider(self, provider: UserProviderObject) -> Scope | None:
        if not isinstance(provider, type):
            # instance handling
            return None

        raise ValueError("Cannot determine scope from provider")


class _SpecVariables:
    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self.type = _SpecVariable(
            name=f"_dep_{spec.slot}_type",
            annotation=type[Any],
        )
        self.resolver = _SpecVariable(
            name=f"_dep_{spec.slot}_resolver",
            annotation=Any,  # todo: can do better with annotation based on kind
        )
        self.threading_lock = _SpecVariable(
            name=f"_dep_{spec.slot}_threading_lock",
            annotation="threading.Lock",
            value="threading.Lock()",
        )
        self.asyncio_lock = _SpecVariable(
            name=f"_dep_{spec.slot}_asyncio_lock",
            annotation="asyncio.Lock",
            value="asyncio.Lock()",
        )

    def __iter__(self) -> Iterator[_SpecVariable]:
        for attr in self.__dict__.values():
            if isinstance(attr, _SpecVariable):
                yield attr


@dataclass(slots=True)
class _SpecVariable:
    name: str
    annotation: Any
    value: Any = ...

    def render(self) -> str:
        var = f"{self.name}: {self.annotation}"
        if self.value is not ...:
            var = f"{var} = {self.value}"

        return var


class Registrations:
    def __init__(self) -> None:
        self._registrations_by_type: dict[UserDependency, ProviderSpec] = {}
        self._registrations_by_slot: dict[int, ProviderSpec] = {}

    def add(self, spec: ProviderSpec) -> None:
        self._registrations_by_type[spec.provides] = spec
        self._registrations_by_slot[spec.slot] = spec

    def get_by_type(self, dep_type: UserDependency) -> ProviderSpec:
        return self._registrations_by_type[dep_type]

    def get_by_slot(self, slot: int) -> ProviderSpec:
        return self._registrations_by_slot[slot]

    def get_by_scope(self, scope: BaseScope | None) -> list[ProviderSpec]:
        return [
            spec
            for spec in self._registrations_by_type.values()
            if spec.scope == scope
        ]

    def values(self) -> list[ProviderSpec]:
        return list(self._registrations_by_type.values())

    def __len__(self) -> int:
        return len(self._registrations_by_type)


ex = _ProviderSpecExtractor()
registrations = Registrations()
registrations.add(ex.extract(provider=42))
registrations.add(
    ex.extract(
        provides=float,
        provider=lambda: 42.69,
        provider_kind=ProviderKind.CALL,
    ),
)
registrations.add(
    ex.extract(
        provider=lambda f: str(f()),
        provides=str,
        provider_kind=ProviderKind.CALL,
        scope=Scope.REQUEST,
        dependencies=[
            ProviderDependency(
                provides=float,
                parameter=inspect.Parameter(
                    name="f",
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=float,
                ),
            ),
        ],
    ),
)

if __name__ == "__main__":
    print(registrations._registrations_by_slot)

    # jinja2 loading
    template = jinja2.Environment().from_string(
        Path(
            "/Users/maksimzayats/dev/diwires/diwire1/src/diwire/resolvers/resolvers.py.jinja2"
        ).read_text(),
    )

    rendered = template.render(
        registrations=registrations,
        Scope=Scope,
        ProviderKind=ProviderKind,
    )

    print(rendered)

    Path("/Users/maksimzayats/dev/diwires/diwire1/src/diwire/resolvers/resolvers_ex.py").write_text(rendered)