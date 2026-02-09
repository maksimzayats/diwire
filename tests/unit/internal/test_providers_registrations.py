from __future__ import annotations

from diwire.providers import Lifetime, ProviderSpec, ProvidersRegistrations
from diwire.scope import BaseScope, Scope


def _provider_spec(*, provides: type[object], scope_level: BaseScope) -> ProviderSpec:
    return ProviderSpec(
        provides=provides,
        instance=provides(),
        lifetime=Lifetime.TRANSIENT,
        scope=scope_level,
        is_async=False,
        is_any_dependency_async=False,
        needs_cleanup=False,
    )


def test_get_by_scope_returns_only_matching_provider_specs() -> None:
    registrations = ProvidersRegistrations()
    app_spec = _provider_spec(provides=type("AppService", (), {}), scope_level=Scope.APP)
    request_spec = _provider_spec(
        provides=type("RequestService", (), {}),
        scope_level=Scope.REQUEST,
    )
    registrations.add(app_spec)
    registrations.add(request_spec)

    app_scope_specs = registrations.get_by_scope(Scope.APP)
    request_scope_specs = registrations.get_by_scope(Scope.REQUEST)

    assert app_scope_specs == [app_spec]
    assert request_scope_specs == [request_spec]


def test_len_returns_total_registered_provider_specs() -> None:
    registrations = ProvidersRegistrations()
    registrations.add(_provider_spec(provides=type("FirstService", (), {}), scope_level=Scope.APP))
    registrations.add(
        _provider_spec(
            provides=type("SecondService", (), {}),
            scope_level=Scope.REQUEST,
        ),
    )

    assert len(registrations) == 2
