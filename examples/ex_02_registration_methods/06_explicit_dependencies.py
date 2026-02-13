"""Focused example: explicit dependency mapping."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from diwire import Container


@dataclass(slots=True)
class UntypedDependency:
    value: str


@dataclass(slots=True)
class ExplicitService:
    raw_dependency: UntypedDependency


def main() -> None:
    container = Container()
    raw = UntypedDependency(value="raw")
    container.add_instance(raw, provides=UntypedDependency)

    def build_service(raw_dependency) -> ExplicitService:  # type: ignore[no-untyped-def]
        return ExplicitService(raw_dependency=raw_dependency)

    signature = inspect.signature(build_service)
    dependencies = {
        UntypedDependency: signature.parameters["raw_dependency"],
    }
    container.add_factory(build_service, provides=ExplicitService, dependencies=dependencies)

    resolved = container.resolve(ExplicitService)
    print(f"explicit_deps_ok={resolved.raw_dependency is raw}")  # => explicit_deps_ok=True


if __name__ == "__main__":
    main()
