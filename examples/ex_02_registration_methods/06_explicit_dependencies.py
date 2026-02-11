"""Focused example: explicit ``ProviderDependency`` mapping."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from diwire import Container
from diwire.providers import ProviderDependency


@dataclass(slots=True)
class UntypedDependency:
    value: str


@dataclass(slots=True)
class ExplicitService:
    raw_dependency: UntypedDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    raw = UntypedDependency(value="raw")
    container.register_instance(UntypedDependency, instance=raw)

    def build_service(raw_dependency) -> ExplicitService:  # type: ignore[no-untyped-def]
        return ExplicitService(raw_dependency=raw_dependency)

    signature = inspect.signature(build_service)
    dependencies = [
        ProviderDependency(
            provides=UntypedDependency,
            parameter=signature.parameters["raw_dependency"],
        ),
    ]
    container.register_factory(ExplicitService, factory=build_service, dependencies=dependencies)

    resolved = container.resolve(ExplicitService)
    print(f"explicit_deps_ok={resolved.raw_dependency is raw}")  # => explicit_deps_ok=True


if __name__ == "__main__":
    main()
