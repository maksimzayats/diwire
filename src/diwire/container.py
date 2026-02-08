from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

import jinja2

from diwire.providers import (
    Lifetime,
    ProviderSpecExtractor,
    ProvidersRegistrations,
    UserDependency,
    UserProviderObject,
    ProviderKind,
)
from diwire.scope import BaseScope, Scope

TUserProviderObject = TypeVar("TUserProviderObject", bound=UserProviderObject)

logger = logging.getLogger(__name__)

class Container:
    """A dependency injection container."""

    def __init__(
        self,
        root_scope: BaseScope = Scope.APP,
        default_lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> None:
        self._root_scope = root_scope
        self._default_lifetime = default_lifetime

        self._provider_spec_extractor = ProviderSpecExtractor(root_scope=self.root_scope)
        self._providers_registrations = ProvidersRegistrations()

    def register(
        self,
        provides: UserDependency | None = None,
        *,
        instance: Any | None = None,
        concrete_type: type[Any] | None = None,
        factory: Callable[..., Any] | Callable[..., Awaitable[Any]] | None = None,
        scope: BaseScope | None = None,
        lifetime: Lifetime | None = None,
    ) -> RegistrationDecorator:
        scope = scope or self._root_scope
        lifetime = lifetime or self._default_lifetime

        if instance is not None and scope != self._root_scope:
            scope = self._root_scope
            logger.warning("Instance registration requires root scope; overriding scope to root scope.")

        if lifetime == Lifetime.SINGLETON and scope != self._root_scope:
            scope = self._root_scope
            logger.warning("Singleton lifetime requires root scope; overriding scope to root scope.")

        if instance is not None:
            spec = self._provider_spec_extractor.extract(
                provider=instance,
                provider_kind=ProviderKind.VALUE,
                provides=provides,
                scope=scope,
                lifetime=lifetime,
                dependencies=[],
            )
        elif factory is not None:
            dependencies = ...

        return RegistrationDecorator(
            container=self,
            provides=provides,
            instance=instance,
        )


class RegistrationDecorator:
    def __init__(
        self,
        container: Container,
        provides: UserDependency | None = None,
        **registration_kwargs: Any,
    ) -> None:
        self._container = container
        self._provides = provides
        self._registration_kwargs = registration_kwargs

    def __call__(self, provider: TUserProviderObject) -> TUserProviderObject:
        if self._provides is not None:
            self._container.register(provides=self._provides, **self._registration_kwargs)

        self._container.register(provides=provider, **self._registration_kwargs)

        return provider


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
            "/Users/maksimzayats/dev/diwires/diwire1/src/diwire/resolvers/resolvers.py.jinja2",
        ).read_text(),
    )

    rendered = template.render(
        registrations=registrations,
        Scope=Scope,
        ProviderKind=ProviderKind,
    )

    print(rendered)

    Path("/Users/maksimzayats/dev/diwires/diwire1/src/diwire/resolvers/resolvers_ex.py").write_text(
        rendered,
    )
