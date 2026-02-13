# Examples

Each topic lives in a grouped folder named `ex_XX_<topic>/`.

The section between `<!-- BEGIN: AUTO-GENERATED EXAMPLES -->` and
`<!-- END: AUTO-GENERATED EXAMPLES -->` is generated from Python files in
`examples/ex_*`. Do not edit that region by hand.

Regenerate it with:

```bash
uv run python -m tools.generate_examples_readme
# or
make examples-readme
```

<!-- BEGIN: AUTO-GENERATED EXAMPLES -->

### Table of Contents

- [01. Quickstart](#ex-01-quickstart)
- [02. Registration Methods](#ex-02-registration-methods)
- [03. Lifetimes](#ex-03-lifetimes)
- [04. Scopes and Cleanup](#ex-04-scopes-and-cleanup)
- [05. Compilation](#ex-05-compilation)
- [06. Function Injection](#ex-06-function-injection)
- [07. Named Components](#ex-07-named-components)
- [08. Open Generics](#ex-08-open-generics)
- [09. Autoregistration](#ex-09-autoregistration)
- [10. Provider Context](#ex-10-provider-context)
- [11. Lock Modes](#ex-11-lock-modes)
- [12. Supported Frameworks](#ex-12-supported-frameworks)
- [13. Pydantic Settings](#ex-13-pydantic-settings)
- [14. Pytest Plugin](#ex-14-pytest-plugin)
- [15. FastAPI](#ex-15-fastapi)
- [16. Errors and Troubleshooting](#ex-16-errors-and-troubleshooting)
- [17. Scope Context Values](#ex-17-scope-context-values)
- [18. Async](#ex-18-async)
- [19. Class Context Managers](#ex-19-class-context-managers)
- [20. Providers](#ex-20-providers)
- [21. Decorators](#ex-21-decorators)
- [22. All Components](#ex-22-all-components)
- [23. Maybe](#ex-23-maybe)

<a id="ex-01-quickstart"></a>
## 01. Quickstart

Files:
- [01_quickstart.py](#ex-01-quickstart--01-quickstart-py)

<a id="ex-01-quickstart--01-quickstart-py"></a>
### 01_quickstart.py ([ex_01_quickstart/01_quickstart.py](ex_01_quickstart/01_quickstart.py))

Quickstart: automatic dependency wiring from type hints.

Start with plain classes, resolve only the top-level service, and see how
diwire builds the full dependency chain for you.

```python
from __future__ import annotations

from diwire import Container


class Database:
    def __init__(self) -> None:
        self.host = "localhost"


class UserRepository:
    def __init__(self, database: Database) -> None:
        self.database = database


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository


def main() -> None:
    container = Container()
    service = container.resolve(UserService)

    print(f"db_host={service.repository.database.host}")  # => db_host=localhost

    chain = (
        f"{type(service).__name__}"
        f">{type(service.repository).__name__}"
        f">{type(service.repository.database).__name__}"
    )
    print(f"chain={chain}")  # => chain=UserService>UserRepository>Database


if __name__ == "__main__":
    main()
```

<a id="ex-02-registration-methods"></a>
## 02. Registration Methods

Files:
- [01_registration_methods.py](#ex-02-registration-methods--01-registration-methods-py)
- [02_add_instance.py](#ex-02-registration-methods--02-add-instance-py)
- [03_add_concrete_factory.py](#ex-02-registration-methods--03-add-concrete-factory-py)
- [04_add_generator_cleanup.py](#ex-02-registration-methods--04-add-generator-cleanup-py)
- [05_add_context_manager_cleanup.py](#ex-02-registration-methods--05-add-context-manager-cleanup-py)
- [06_explicit_dependencies.py](#ex-02-registration-methods--06-explicit-dependencies-py)

<a id="ex-02-registration-methods--01-registration-methods-py"></a>
### 01_registration_methods.py ([ex_02_registration_methods/01_registration_methods.py](ex_02_registration_methods/01_registration_methods.py))

Registration methods from basic to advanced.

Learn when to use:

1. ``add_instance`` for pre-built objects.
2. ``add_concrete`` for constructor-based creation.
3. ``add_factory`` for custom build logic.
4. ``add_generator`` for resources with teardown on scope exit.
5. ``add_context_manager`` for context-managed resources.
6. Explicit ``dependencies={dependency_key: inspect.Parameter(...)}`` to bypass inference.

```python
from __future__ import annotations

import inspect
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from diwire import Container, Lifetime, Scope


@dataclass(slots=True)
class Config:
    value: str


class ConcreteDependency:
    pass


@dataclass(slots=True)
class FactoryService:
    dependency: ConcreteDependency


class GeneratorResource:
    pass


class ContextManagerResource:
    pass


@dataclass(slots=True)
class UntypedDependency:
    value: str


@dataclass(slots=True)
class ExplicitDependencyService:
    raw_dependency: UntypedDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    config = Config(value="singleton")
    container.add_instance(config, provides=Config)
    instance_singleton = container.resolve(Config) is container.resolve(Config)
    print(f"instance_singleton={instance_singleton}")  # => instance_singleton=True

    container.add_concrete(ConcreteDependency, provides=ConcreteDependency)

    def build_factory(dependency: ConcreteDependency) -> FactoryService:
        return FactoryService(dependency=dependency)

    container.add_factory(build_factory, provides=FactoryService)
    factory_result = container.resolve(FactoryService)
    print(
        f"factory_injected_dep={isinstance(factory_result.dependency, ConcreteDependency)}",
    )  # => factory_injected_dep=True

    generator_state = {"cleaned": False}

    def build_generator_resource() -> Generator[GeneratorResource, None, None]:
        try:
            yield GeneratorResource()
        finally:
            generator_state["cleaned"] = True

    container.add_generator(
        build_generator_resource,
        provides=GeneratorResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(GeneratorResource)
    print(f"generator_cleaned={generator_state['cleaned']}")  # => generator_cleaned=True

    context_state = {"cleaned": False}

    @contextmanager
    def build_context_resource() -> Generator[ContextManagerResource, None, None]:
        try:
            yield ContextManagerResource()
        finally:
            context_state["cleaned"] = True

    container.add_context_manager(
        build_context_resource,
        provides=ContextManagerResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(ContextManagerResource)
    print(f"context_manager_cleaned={context_state['cleaned']}")  # => context_manager_cleaned=True

    raw_dependency = UntypedDependency(value="raw")
    container.add_instance(raw_dependency, provides=UntypedDependency)

    def build_explicit_service(raw_dependency) -> ExplicitDependencyService:  # type: ignore[no-untyped-def]
        return ExplicitDependencyService(raw_dependency=raw_dependency)

    signature = inspect.signature(build_explicit_service)
    explicit_dependencies = {
        UntypedDependency: signature.parameters["raw_dependency"],
    }
    container.add_factory(
        build_explicit_service,
        provides=ExplicitDependencyService,
        dependencies=explicit_dependencies,
    )
    explicit_service = container.resolve(ExplicitDependencyService)
    print(
        f"explicit_deps_ok={explicit_service.raw_dependency is raw_dependency}",
    )  # => explicit_deps_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-02-registration-methods--02-add-instance-py"></a>
### 02_add_instance.py ([ex_02_registration_methods/02_add_instance.py](ex_02_registration_methods/02_add_instance.py))

Focused example: ``add_instance`` for pre-built objects.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


@dataclass(slots=True)
class Config:
    value: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    config = Config(value="singleton")
    container.add_instance(config, provides=Config)

    first = container.resolve(Config)
    second = container.resolve(Config)
    print(f"instance_singleton={first is second}")  # => instance_singleton=True


if __name__ == "__main__":
    main()
```

<a id="ex-02-registration-methods--03-add-concrete-factory-py"></a>
### 03_add_concrete_factory.py ([ex_02_registration_methods/03_add_concrete_factory.py](ex_02_registration_methods/03_add_concrete_factory.py))

Focused example: ``add_concrete`` and ``add_factory`` together.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class ConcreteDependency:
    pass


@dataclass(slots=True)
class FactoryService:
    dependency: ConcreteDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(ConcreteDependency, provides=ConcreteDependency)

    def build_service(dependency: ConcreteDependency) -> FactoryService:
        return FactoryService(dependency=dependency)

    container.add_factory(build_service, provides=FactoryService)
    resolved = container.resolve(FactoryService)
    print(
        f"factory_injected_dep={isinstance(resolved.dependency, ConcreteDependency)}",
    )  # => factory_injected_dep=True


if __name__ == "__main__":
    main()
```

<a id="ex-02-registration-methods--04-add-generator-cleanup-py"></a>
### 04_add_generator_cleanup.py ([ex_02_registration_methods/04_add_generator_cleanup.py](ex_02_registration_methods/04_add_generator_cleanup.py))

Focused example: ``add_generator`` cleanup on scope exit.

```python
from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope


class Resource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"cleaned": False}

    def provide_resource() -> Generator[Resource, None, None]:
        try:
            yield Resource()
        finally:
            state["cleaned"] = True

    container.add_generator(
        provide_resource,
        provides=Resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(Resource)

    print(f"generator_cleaned={state['cleaned']}")  # => generator_cleaned=True


if __name__ == "__main__":
    main()
```

<a id="ex-02-registration-methods--05-add-context-manager-cleanup-py"></a>
### 05_add_context_manager_cleanup.py ([ex_02_registration_methods/05_add_context_manager_cleanup.py](ex_02_registration_methods/05_add_context_manager_cleanup.py))

Focused example: ``add_context_manager`` cleanup on scope exit.

```python
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from diwire import Container, Lifetime, Scope


class Resource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"cleaned": False}

    @contextmanager
    def provide_resource() -> Generator[Resource, None, None]:
        try:
            yield Resource()
        finally:
            state["cleaned"] = True

    container.add_context_manager(
        provide_resource,
        provides=Resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(Resource)

    print(f"context_manager_cleaned={state['cleaned']}")  # => context_manager_cleaned=True


if __name__ == "__main__":
    main()
```

<a id="ex-02-registration-methods--06-explicit-dependencies-py"></a>
### 06_explicit_dependencies.py ([ex_02_registration_methods/06_explicit_dependencies.py](ex_02_registration_methods/06_explicit_dependencies.py))

Focused example: explicit dependency mapping.

```python
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
    container = Container(autoregister_concrete_types=False)
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
```

<a id="ex-03-lifetimes"></a>
## 03. Lifetimes

Files:
- [01_lifetimes.py](#ex-03-lifetimes--01-lifetimes-py)

<a id="ex-03-lifetimes--01-lifetimes-py"></a>
### 01_lifetimes.py ([ex_03_lifetimes/01_lifetimes.py](ex_03_lifetimes/01_lifetimes.py))

Lifetimes: ``TRANSIENT`` and ``SCOPED``.

See how object identity changes across repeated resolves and scope boundaries,
including root-scoped ``SCOPED`` singleton behavior.

```python
from __future__ import annotations

from diwire import Container, Lifetime, Scope


class TransientService:
    pass


class SingletonService:
    pass


class ScopedService:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_concrete(
        TransientService,
        provides=TransientService,
        lifetime=Lifetime.TRANSIENT,
    )
    transient_first = container.resolve(TransientService)
    transient_second = container.resolve(TransientService)
    print(f"transient_new={transient_first is not transient_second}")  # => transient_new=True

    container.add_concrete(
        SingletonService,
        provides=SingletonService,
        lifetime=Lifetime.SCOPED,
    )
    singleton_first = container.resolve(SingletonService)
    singleton_second = container.resolve(SingletonService)
    print(f"singleton_same={singleton_first is singleton_second}")  # => singleton_same=True

    container.add_concrete(
        ScopedService,
        provides=ScopedService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        scoped_first = request_scope.resolve(ScopedService)
        scoped_second = request_scope.resolve(ScopedService)

    with container.enter_scope() as request_scope:
        scoped_third = request_scope.resolve(ScopedService)

    print(f"scoped_same_within={scoped_first is scoped_second}")  # => scoped_same_within=True
    print(f"scoped_diff_across={scoped_first is not scoped_third}")  # => scoped_diff_across=True


if __name__ == "__main__":
    main()
```

<a id="ex-04-scopes-and-cleanup"></a>
## 04. Scopes and Cleanup

Files:
- [01_scopes_and_cleanup.py](#ex-04-scopes-and-cleanup--01-scopes-and-cleanup-py)
- [02_scope_transitions.py](#ex-04-scopes-and-cleanup--02-scope-transitions-py)
- [03_scope_mismatch.py](#ex-04-scopes-and-cleanup--03-scope-mismatch-py)
- [04_scoped_cleanup.py](#ex-04-scopes-and-cleanup--04-scoped-cleanup-py)
- [05_singleton_cleanup.py](#ex-04-scopes-and-cleanup--05-singleton-cleanup-py)

<a id="ex-04-scopes-and-cleanup--01-scopes-and-cleanup-py"></a>
### 01_scopes_and_cleanup.py ([ex_04_scopes_and_cleanup/01_scopes_and_cleanup.py](ex_04_scopes_and_cleanup/01_scopes_and_cleanup.py))

Scopes and cleanup behavior across transitions and lifetimes.

This module covers:

1. Default ``enter_scope()`` transition behavior (skippable scopes).
2. Explicit ``enter_scope(Scope.SESSION)`` and ``enter_scope(Scope.ACTION)``.
3. ``DIWireScopeMismatchError`` when resolving a scoped dependency from root.
4. Scoped cleanup timing (on scope exit).
5. Singleton cleanup timing (on ``container.close()``).

```python
from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireScopeMismatchError


class RequestScopedDependency:
    pass


class ScopedResource:
    pass


class SingletonResource:
    pass


def _resolver_scope_name(resolver: object) -> str:
    inner_resolver = getattr(resolver, "_resolver", resolver)
    class_name = type(inner_resolver).__name__
    return class_name.removeprefix("_").removesuffix("Resolver").upper()


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_concrete(
        RequestScopedDependency,
        provides=RequestScopedDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as default_scope:
        default_scope_name = _resolver_scope_name(default_scope)
    print(f"enter_scope_default={default_scope_name}")  # => enter_scope_default=REQUEST

    with container.enter_scope(Scope.ACTION) as action_scope:
        resolved_in_action = action_scope.resolve(RequestScopedDependency)
    print(
        f"action_scope_can_resolve_request_scoped={isinstance(resolved_in_action, RequestScopedDependency)}",
    )  # => action_scope_can_resolve_request_scoped=True

    try:
        container.resolve(RequestScopedDependency)
    except DIWireScopeMismatchError as error:
        mismatch_error_name = type(error).__name__
    print(
        f"scope_mismatch_error={mismatch_error_name}",
    )  # => scope_mismatch_error=DIWireScopeMismatchError

    scoped_state = {"opened": 0, "closed": 0}

    def provide_scoped_resource() -> Generator[ScopedResource, None, None]:
        scoped_state["opened"] += 1
        try:
            yield ScopedResource()
        finally:
            scoped_state["closed"] += 1

    container.add_generator(
        provide_scoped_resource,
        provides=ScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(ScopedResource)
        closed_while_scope_open = scoped_state["closed"]

    scoped_cleanup_after_exit = closed_while_scope_open == 0 and scoped_state["closed"] == 1
    print(
        f"scoped_cleanup_after_exit={scoped_cleanup_after_exit}",
    )  # => scoped_cleanup_after_exit=True

    singleton_state = {"opened": 0, "closed": 0}

    def provide_singleton_resource() -> Generator[SingletonResource, None, None]:
        singleton_state["opened"] += 1
        try:
            yield SingletonResource()
        finally:
            singleton_state["closed"] += 1

    container.add_generator(
        provide_singleton_resource,
        provides=SingletonResource,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )
    _ = container.resolve(SingletonResource)
    closed_before_close = singleton_state["closed"]
    container.close()
    singleton_cleanup_on_close = closed_before_close == 0 and singleton_state["closed"] == 1
    print(
        f"singleton_cleanup_on_close={singleton_cleanup_on_close}",
    )  # => singleton_cleanup_on_close=True


if __name__ == "__main__":
    main()
```

<a id="ex-04-scopes-and-cleanup--02-scope-transitions-py"></a>
### 02_scope_transitions.py ([ex_04_scopes_and_cleanup/02_scope_transitions.py](ex_04_scopes_and_cleanup/02_scope_transitions.py))

Focused example: default and explicit scope transitions.

```python
from __future__ import annotations

from diwire import Container, Lifetime, Scope


class RequestDependency:
    pass


def _resolver_scope_name(resolver: object) -> str:
    return type(resolver).__name__.removeprefix("_").removesuffix("Resolver").upper()


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        default_scope = _resolver_scope_name(request_scope)

    with container.enter_scope(Scope.ACTION) as action_scope:
        resolved = action_scope.resolve(RequestDependency)

    print(f"enter_scope_default={default_scope}")  # => enter_scope_default=REQUEST
    print(
        f"action_scope_can_resolve_request_scoped={isinstance(resolved, RequestDependency)}",
    )  # => action_scope_can_resolve_request_scoped=True


if __name__ == "__main__":
    main()
```

<a id="ex-04-scopes-and-cleanup--03-scope-mismatch-py"></a>
### 03_scope_mismatch.py ([ex_04_scopes_and_cleanup/03_scope_mismatch.py](ex_04_scopes_and_cleanup/03_scope_mismatch.py))

Focused example: ``DIWireScopeMismatchError`` from root resolution.

```python
from __future__ import annotations

from diwire import Container, Scope
from diwire.exceptions import DIWireScopeMismatchError


class RequestDependency:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
    )

    try:
        container.resolve(RequestDependency)
    except DIWireScopeMismatchError as error:
        error_name = type(error).__name__

    print(f"scope_mismatch_error={error_name}")  # => scope_mismatch_error=DIWireScopeMismatchError


if __name__ == "__main__":
    main()
```

<a id="ex-04-scopes-and-cleanup--04-scoped-cleanup-py"></a>
### 04_scoped_cleanup.py ([ex_04_scopes_and_cleanup/04_scoped_cleanup.py](ex_04_scopes_and_cleanup/04_scoped_cleanup.py))

Focused example: scoped resource cleanup on scope exit.

```python
from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope


class ScopedResource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"closed": 0}

    def provide_resource() -> Generator[ScopedResource, None, None]:
        try:
            yield ScopedResource()
        finally:
            state["closed"] += 1

    container.add_generator(
        provide_resource,
        provides=ScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope() as request_scope:
        _ = request_scope.resolve(ScopedResource)
        closed_inside_scope = state["closed"]

    closed_after_exit = state["closed"]
    print(
        f"scoped_cleanup_after_exit={closed_inside_scope == 0 and closed_after_exit == 1}",
    )  # => scoped_cleanup_after_exit=True


if __name__ == "__main__":
    main()
```

<a id="ex-04-scopes-and-cleanup--05-singleton-cleanup-py"></a>
### 05_singleton_cleanup.py ([ex_04_scopes_and_cleanup/05_singleton_cleanup.py](ex_04_scopes_and_cleanup/05_singleton_cleanup.py))

Focused example: singleton generator cleanup on ``container.close()``.

```python
from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Lifetime, Scope


class SingletonResource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"closed": 0}

    def provide_resource() -> Generator[SingletonResource, None, None]:
        try:
            yield SingletonResource()
        finally:
            state["closed"] += 1

    container.add_generator(
        provide_resource,
        provides=SingletonResource,
        scope=Scope.APP,
        lifetime=Lifetime.SCOPED,
    )

    _ = container.resolve(SingletonResource)
    closed_before = state["closed"]
    container.close()
    print(
        f"singleton_cleanup_on_close={closed_before == 0 and state['closed'] == 1}",
    )  # => singleton_cleanup_on_close=True


if __name__ == "__main__":
    main()
```

<a id="ex-05-compilation"></a>
## 05. Compilation

Files:
- [01_compilation.py](#ex-05-compilation--01-compilation-py)

<a id="ex-05-compilation--01-compilation-py"></a>
### 01_compilation.py ([ex_05_compilation/01_compilation.py](ex_05_compilation/01_compilation.py))

Compilation caching and invalidation.

``Container.compile()`` caches a root resolver for the current provider graph.
When registrations change, compilation is invalidated and a new resolver is
built on the next compile/resolve call.

```python
from __future__ import annotations

from diwire import Container


class FirstService:
    pass


class SecondService:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(FirstService, provides=FirstService)

    compiled_first = container.compile()
    compiled_second = container.compile()
    print(f"compile_cached={compiled_first is compiled_second}")  # => compile_cached=True

    container.add_concrete(SecondService, provides=SecondService)
    compiled_third = container.compile()
    print(
        f"compile_invalidated={compiled_third is not compiled_first}",
    )  # => compile_invalidated=True


if __name__ == "__main__":
    main()
```

<a id="ex-06-function-injection"></a>
## 06. Function Injection

Files:
- [01_function_injection.py](#ex-06-function-injection--01-function-injection-py)
- [02_function_injection_async_details.py](#ex-06-function-injection--02-function-injection-async-details-py)
- [03_signature_filtering.py](#ex-06-function-injection--03-signature-filtering-py)
- [04_override_injected.py](#ex-06-function-injection--04-override-injected-py)
- [05_auto_open_scope_cleanup.py](#ex-06-function-injection--05-auto-open-scope-cleanup-py)
- [06_nested_wrappers.py](#ex-06-function-injection--06-nested-wrappers-py)

<a id="ex-06-function-injection--01-function-injection-py"></a>
### 01_function_injection.py ([ex_06_function_injection/01_function_injection.py](ex_06_function_injection/01_function_injection.py))

Function injection from basic marker usage to nested wrapper behavior.

This topic demonstrates:

1. ``Injected[T]`` marker semantics and signature filtering.
2. ``@provider_context.inject`` behavior with caller overrides.
3. ``auto_open_scope`` cleanup for scoped generator resources.
4. Nested injected wrappers as providers sharing the same active resolver.

```python
from __future__ import annotations

import inspect
from collections.abc import Generator
from dataclasses import dataclass

from diwire import Container, Injected, Lifetime, Scope, provider_context


@dataclass(slots=True)
class User:
    email: str
    name: str


class RequestScopedResource:
    pass


class RequestDependency:
    pass


@dataclass(slots=True)
class NestedInnerService:
    dependency: RequestDependency


@dataclass(slots=True)
class NestedOuterService:
    inner: NestedInnerService
    dependency: RequestDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(
        User(email="injected@example.com", name="Injected"),
        provides=User,
    )

    @provider_context.inject
    def render_user(
        user_email: str,
        user: Injected[User],
        user_name: str,
    ) -> str:
        return f"{user_email}|{user_name}|{user.email}"

    signature = "('" + "','".join(inspect.signature(render_user).parameters) + "')"
    print(f"signature={signature}")  # => signature=('user_email','user_name')

    injected_result = render_user("contact@example.com", user_name="Alex")
    print(
        f"injected_call_ok={injected_result == 'contact@example.com|Alex|injected@example.com'}",
    )  # => injected_call_ok=True

    overridden_user = User(email="override@example.com", name="Override")
    override_result = render_user(
        "contact@example.com",
        user_name="Alex",
        user=overridden_user,
    )
    print(
        f"override_ok={override_result == 'contact@example.com|Alex|override@example.com'}",
    )  # => override_ok=True

    cleanup_state = {"cleaned": False}

    def provide_scoped_resource() -> Generator[RequestScopedResource, None, None]:
        try:
            yield RequestScopedResource()
        finally:
            cleanup_state["cleaned"] = True

    container.add_generator(
        provide_scoped_resource,
        provides=RequestScopedResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @provider_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def use_scoped_resource(resource: Injected[RequestScopedResource]) -> RequestScopedResource:
        return resource

    _ = use_scoped_resource()
    print(f"auto_scope_cleanup={cleanup_state['cleaned']}")  # => auto_scope_cleanup=True

    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @provider_context.inject
    def build_inner(dependency: Injected[RequestDependency]) -> NestedInnerService:
        return NestedInnerService(dependency=dependency)

    @provider_context.inject
    def build_outer(
        inner: Injected[NestedInnerService],
        dependency: Injected[RequestDependency],
    ) -> NestedOuterService:
        return NestedOuterService(inner=inner, dependency=dependency)

    container.add_factory(
        build_inner,
        provides=NestedInnerService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_outer,
        provides=NestedOuterService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        nested = request_scope.resolve(NestedOuterService)

    print(
        f"nested_scope_identity={nested.inner.dependency is nested.dependency}",
    )  # => nested_scope_identity=True


if __name__ == "__main__":
    main()
```

<a id="ex-06-function-injection--02-function-injection-async-details-py"></a>
### 02_function_injection_async_details.py ([ex_06_function_injection/02_function_injection_async_details.py](ex_06_function_injection/02_function_injection_async_details.py))

Async function-injection deep dive.

Extends ``01_function_injection.py`` with:

- async callables using ``Injected[T]``
- async provider resolution paths
- caller overrides for injected async parameters

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from diwire import Container, Injected, provider_context


@dataclass(slots=True)
class AsyncUser:
    email: str


async def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(AsyncUser(email="async@example.com"))

    @provider_context.inject
    async def handler(user: Injected[AsyncUser]) -> str:
        return user.email

    default_value = await handler()
    overridden_value = await handler(user=AsyncUser(email="override@example.com"))

    if default_value != "async@example.com":
        msg = "Unexpected default async injection result"
        raise TypeError(msg)
    if overridden_value != "override@example.com":
        msg = "Unexpected async override injection result"
        raise TypeError(msg)


if __name__ == "__main__":
    asyncio.run(main())
```

<a id="ex-06-function-injection--03-signature-filtering-py"></a>
### 03_signature_filtering.py ([ex_06_function_injection/03_signature_filtering.py](ex_06_function_injection/03_signature_filtering.py))

Focused example: ``Injected[T]`` and public signature filtering.

```python
from __future__ import annotations

import inspect
from dataclasses import dataclass

from diwire import Container, Injected, provider_context


@dataclass(slots=True)
class User:
    email: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(User(email="user@example.com"))

    @provider_context.inject
    def handler(user_email: str, user: Injected[User], user_name: str) -> str:
        return f"{user_email}|{user_name}|{user.email}"

    signature = "('" + "','".join(inspect.signature(handler).parameters) + "')"
    print(f"signature={signature}")  # => signature=('user_email','user_name')


if __name__ == "__main__":
    main()
```

<a id="ex-06-function-injection--04-override-injected-py"></a>
### 04_override_injected.py ([ex_06_function_injection/04_override_injected.py](ex_06_function_injection/04_override_injected.py))

Focused example: caller override for injected parameters.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, provider_context


@dataclass(slots=True)
class User:
    email: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(User(email="container@example.com"))

    @provider_context.inject
    def handler(user: Injected[User]) -> str:
        return user.email

    default_value = handler()
    override_value = handler(user=User(email="override@example.com"))

    print(f"default_injected={default_value}")  # => default_injected=container@example.com
    print(f"override_injected={override_value}")  # => override_injected=override@example.com


if __name__ == "__main__":
    main()
```

<a id="ex-06-function-injection--05-auto-open-scope-cleanup-py"></a>
### 05_auto_open_scope_cleanup.py ([ex_06_function_injection/05_auto_open_scope_cleanup.py](ex_06_function_injection/05_auto_open_scope_cleanup.py))

Focused example: ``auto_open_scope`` with scoped cleanup.

```python
from __future__ import annotations

from collections.abc import Generator

from diwire import Container, Injected, Lifetime, Scope, provider_context


class Resource:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    state = {"cleaned": False}

    def provide_resource() -> Generator[Resource, None, None]:
        try:
            yield Resource()
        finally:
            state["cleaned"] = True

    container.add_generator(
        provide_resource,
        provides=Resource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @provider_context.inject(scope=Scope.REQUEST, auto_open_scope=True)
    def handler(resource: Injected[Resource]) -> Resource:
        return resource

    _ = handler()
    print(f"auto_scope_cleanup={state['cleaned']}")  # => auto_scope_cleanup=True


if __name__ == "__main__":
    main()
```

<a id="ex-06-function-injection--06-nested-wrappers-py"></a>
### 06_nested_wrappers.py ([ex_06_function_injection/06_nested_wrappers.py](ex_06_function_injection/06_nested_wrappers.py))

Focused example: nested injected wrappers share one active resolver.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, Lifetime, Scope, provider_context


class RequestDependency:
    pass


@dataclass(slots=True)
class InnerService:
    dependency: RequestDependency


@dataclass(slots=True)
class OuterService:
    inner: InnerService
    dependency: RequestDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @provider_context.inject
    def build_inner(dependency: Injected[RequestDependency]) -> InnerService:
        return InnerService(dependency=dependency)

    @provider_context.inject
    def build_outer(
        inner: Injected[InnerService],
        dependency: Injected[RequestDependency],
    ) -> OuterService:
        return OuterService(inner=inner, dependency=dependency)

    container.add_factory(
        build_inner,
        provides=InnerService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    container.add_factory(
        build_outer,
        provides=OuterService,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        resolved = request_scope.resolve(OuterService)

    print(
        f"nested_scope_identity={resolved.inner.dependency is resolved.dependency}",
    )  # => nested_scope_identity=True


if __name__ == "__main__":
    main()
```

<a id="ex-07-named-components"></a>
## 07. Named Components

Files:
- [01_named_components.py](#ex-07-named-components--01-named-components-py)
- [02_component_registration_shortcut.py](#ex-07-named-components--02-component-registration-shortcut-py)

<a id="ex-07-named-components--01-named-components-py"></a>
### 01_named_components.py ([ex_07_named_components/01_named_components.py](ex_07_named_components/01_named_components.py))

Named components with ``Component("name")`` and ``Annotated`` keys.

This module demonstrates how to register multiple implementations of the same
base type and resolve/inject them using component-qualified dependency keys.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container, Injected, provider_context


@dataclass(slots=True)
class UserStore:
    backend: str

    def get_user(self, user_id: int) -> str:
        return f"{self.backend}:user:{user_id}"


PrimaryStore = Annotated[UserStore, Component("primary")]
FallbackStore = Annotated[UserStore, Component("fallback")]


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_factory(lambda: UserStore(backend="redis"), provides=PrimaryStore)
    container.add_factory(lambda: UserStore(backend="memory"), provides=FallbackStore)

    @provider_context.inject
    def load_users(
        primary_store: Injected[PrimaryStore],
        fallback_store: Injected[FallbackStore],
    ) -> tuple[str, str]:
        return primary_store.get_user(1), fallback_store.get_user(1)

    primary_user, fallback_user = load_users()
    print(f"primary={primary_user}")  # => primary=redis:user:1
    print(f"fallback={fallback_user}")  # => fallback=memory:user:1


if __name__ == "__main__":
    main()
```

<a id="ex-07-named-components--02-component-registration-shortcut-py"></a>
### 02_component_registration_shortcut.py ([ex_07_named_components/02_component_registration_shortcut.py](ex_07_named_components/02_component_registration_shortcut.py))

Register components ergonomically with ``component=...``.

This example shows that registration can use ``component=...`` while runtime
resolution and injection keys remain ``Annotated[..., Component(...)]``.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container, Injected, provider_context


@dataclass(slots=True)
class Cache:
    backend: str


PrimaryCache = Annotated[Cache, Component("primary")]
FallbackCache = Annotated[Cache, Component("fallback")]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(Cache(backend="redis"), provides=Cache, component="primary")
    container.add_instance(Cache(backend="memory"), provides=Cache, component=Component("fallback"))

    @provider_context.inject
    def load(
        primary: Injected[PrimaryCache],
        fallback: Injected[FallbackCache],
    ) -> tuple[str, str]:
        return primary.backend, fallback.backend

    primary_backend, fallback_backend = load()
    print(f"primary={primary_backend}")  # => primary=redis
    print(f"fallback={fallback_backend}")  # => fallback=memory
    print(f"resolved={container.resolve(PrimaryCache).backend}")  # => resolved=redis


if __name__ == "__main__":
    main()
```

<a id="ex-08-open-generics"></a>
## 08. Open Generics

Files:
- [01_open_generics.py](#ex-08-open-generics--01-open-generics-py)
- [02_open_generics_constraints_details.py](#ex-08-open-generics--02-open-generics-constraints-details-py)
- [03_factory_type_argument.py](#ex-08-open-generics--03-factory-type-argument-py)
- [04_closed_override.py](#ex-08-open-generics--04-closed-override-py)
- [05_specificity_winner.py](#ex-08-open-generics--05-specificity-winner-py)
- [06_scoped_open_generics.py](#ex-08-open-generics--06-scoped-open-generics-py)

<a id="ex-08-open-generics--01-open-generics-py"></a>
### 01_open_generics.py ([ex_08_open_generics/01_open_generics.py](ex_08_open_generics/01_open_generics.py))

Open generics: registration, specificity, overrides, and validation.

This module covers progressively advanced open-generic behavior:

1. Open generic factory registration and type-argument injection.
2. Closed generic override precedence.
3. Most-specific template winner (``Repo[list[U]]`` over ``Repo[T]``).
4. TypeVar bound validation errors.
5. Scoped open-generic resolution requiring a matching opened scope.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError, DIWireScopeMismatchError

T = TypeVar("T")
U = TypeVar("U")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


class _SpecialIntBox(IBox[int]):
    pass


def build_box(type_arg: type[T]) -> IBox[T]:
    return Box(type_arg=type_arg)


class Repo(Generic[T]):
    pass


@dataclass(slots=True)
class GenericRepo(Repo[T]):
    dependency_type: type[T]


@dataclass(slots=True)
class ListRepo(Repo[list[U]]):
    item_type: type[U]


class Model:
    pass


class User(Model):
    pass


M = TypeVar("M", bound=Model)


class ModelBox(Generic[M]):
    pass


@dataclass(slots=True)
class DefaultModelBox(ModelBox[M]):
    type_arg: type[M]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(build_box, provides=IBox)

    box_int = cast("Box[int]", container.resolve(IBox[int]))
    print(f"box_int={box_int.type_arg.__name__}")  # => box_int=int

    container.add_concrete(_SpecialIntBox, provides=IBox[int])
    override = container.resolve(IBox[int])
    print(f"override={type(override).__name__}")  # => override=_SpecialIntBox

    container.add_concrete(GenericRepo, provides=Repo)
    container.add_concrete(ListRepo, provides=Repo[list[U]])
    specific_repo = cast("ListRepo[int]", container.resolve(Repo[list[int]]))
    print(f"specificity_item={specific_repo.item_type.__name__}")  # => specificity_item=int

    validation_container = Container(autoregister_concrete_types=False)
    validation_container.add_concrete(DefaultModelBox, provides=ModelBox)
    invalid_key = cast("Any", ModelBox)[str]
    try:
        validation_container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError as error:
        invalid_generic = type(error).__name__
    print(
        f"invalid_generic={invalid_generic}",
    )  # => invalid_generic=DIWireInvalidGenericTypeArgumentError

    scoped_container = Container(autoregister_concrete_types=False)
    scoped_container.add_factory(
        build_box,
        provides=IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )
    try:
        scoped_container.resolve(IBox[int])
    except DIWireScopeMismatchError:
        scoped_requires_scope = True
    else:
        scoped_requires_scope = False
    print(f"scoped_requires_scope={scoped_requires_scope}")  # => scoped_requires_scope=True


if __name__ == "__main__":
    main()
```

<a id="ex-08-open-generics--02-open-generics-constraints-details-py"></a>
### 02_open_generics_constraints_details.py ([ex_08_open_generics/02_open_generics_constraints_details.py](ex_08_open_generics/02_open_generics_constraints_details.py))

Open-generics constraints deep dive.

Extends ``01_open_generics.py`` with constrained ``TypeVar`` examples and shows
both valid and invalid resolutions.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError

Allowed = TypeVar("Allowed", int, str)


class ConstrainedBox(Generic[Allowed]):
    pass


@dataclass(slots=True)
class ConstrainedBoxImpl(ConstrainedBox[Allowed]):
    type_arg: type[Allowed]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(ConstrainedBoxImpl, provides=ConstrainedBox)

    valid_int = container.resolve(ConstrainedBox[int])
    valid_str = container.resolve(ConstrainedBox[str])

    if cast("ConstrainedBoxImpl[int]", valid_int).type_arg is not int:
        msg = "Expected int constrained type argument"
        raise TypeError(msg)
    if cast("ConstrainedBoxImpl[str]", valid_str).type_arg is not str:
        msg = "Expected str constrained type argument"
        raise TypeError(msg)

    invalid_key = cast("Any", ConstrainedBox)[float]
    try:
        container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError:
        return

    msg = "Expected DIWireInvalidGenericTypeArgumentError for constrained TypeVar"
    raise TypeError(msg)


if __name__ == "__main__":
    main()
```

<a id="ex-08-open-generics--03-factory-type-argument-py"></a>
### 03_factory_type_argument.py ([ex_08_open_generics/03_factory_type_argument.py](ex_08_open_generics/03_factory_type_argument.py))

Focused example: open generic factory with ``type[T]`` injection.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from diwire import Container

T = TypeVar("T")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


def build_box(type_arg: type[T]) -> IBox[T]:
    return Box(type_arg=type_arg)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(build_box, provides=IBox)

    resolved = cast("Box[int]", container.resolve(IBox[int]))
    print(f"box_int={resolved.type_arg.__name__}")  # => box_int=int


if __name__ == "__main__":
    main()
```

<a id="ex-08-open-generics--04-closed-override-py"></a>
### 04_closed_override.py ([ex_08_open_generics/04_closed_override.py](ex_08_open_generics/04_closed_override.py))

Focused example: closed generic override beats open template.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from diwire import Container

T = TypeVar("T")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


class _SpecialIntBox(IBox[int]):
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(Box, provides=IBox)
    container.add_concrete(_SpecialIntBox, provides=IBox[int])

    resolved = container.resolve(IBox[int])
    print(f"override={type(resolved).__name__}")  # => override=_SpecialIntBox


if __name__ == "__main__":
    main()
```

<a id="ex-08-open-generics--05-specificity-winner-py"></a>
### 05_specificity_winner.py ([ex_08_open_generics/05_specificity_winner.py](ex_08_open_generics/05_specificity_winner.py))

Focused example: most-specific open template selection.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from diwire import Container

T = TypeVar("T")
U = TypeVar("U")


class Repo(Generic[T]):
    pass


@dataclass(slots=True)
class GenericRepo(Repo[T]):
    dependency_type: type[T]


@dataclass(slots=True)
class ListRepo(Repo[list[U]]):
    item_type: type[U]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(GenericRepo, provides=Repo)
    container.add_concrete(ListRepo, provides=Repo[list[U]])

    resolved = cast("ListRepo[int]", container.resolve(Repo[list[int]]))
    print(f"specificity_item={resolved.item_type.__name__}")  # => specificity_item=int


if __name__ == "__main__":
    main()
```

<a id="ex-08-open-generics--06-scoped-open-generics-py"></a>
### 06_scoped_open_generics.py ([ex_08_open_generics/06_scoped_open_generics.py](ex_08_open_generics/06_scoped_open_generics.py))

Focused example: scoped open generics require an opened scope.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireScopeMismatchError

T = TypeVar("T")


class IBox(Generic[T]):
    pass


@dataclass(slots=True)
class Box(IBox[T]):
    type_arg: type[T]


def build_box(type_arg: type[T]) -> IBox[T]:
    return Box(type_arg=type_arg)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(
        build_box,
        provides=IBox,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    try:
        container.resolve(IBox[int])
    except DIWireScopeMismatchError:
        requires_scope = True
    else:
        requires_scope = False

    print(f"scoped_requires_scope={requires_scope}")  # => scoped_requires_scope=True


if __name__ == "__main__":
    main()
```

<a id="ex-09-autoregistration"></a>
## 09. Autoregistration

Files:
- [01_autoregistration.py](#ex-09-autoregistration--01-autoregistration-py)
- [02_resolve_chain.py](#ex-09-autoregistration--02-resolve-chain-py)
- [03_add_dependency_autoregister.py](#ex-09-autoregistration--03-add-dependency-autoregister-py)
- [04_strict_mode.py](#ex-09-autoregistration--04-strict-mode-py)
- [05_uuid_special_type.py](#ex-09-autoregistration--05-uuid-special-type-py)

<a id="ex-09-autoregistration--01-autoregistration-py"></a>
### 01_autoregistration.py ([ex_09_autoregistration/01_autoregistration.py](ex_09_autoregistration/01_autoregistration.py))

Autoregistration behaviors at resolve-time and registration-time.

This module demonstrates:

1. Resolve-time concrete autoregistration for dependency chains.
2. Registration-time dependency autoregistration via
   ``autoregister_dependencies=True``.
3. Strict mode behavior when ``autoregister_concrete_types=False``.
4. Skipped/special types (``uuid.UUID``) that require explicit registration.

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError


class AutoregLeaf:
    pass


@dataclass(slots=True)
class AutoregBranch:
    leaf: AutoregLeaf


@dataclass(slots=True)
class AutoregRoot:
    branch: AutoregBranch


class RegisterDependency:
    pass


@dataclass(slots=True)
class RegisterRoot:
    dependency: RegisterDependency


@dataclass(slots=True)
class StrictRoot:
    dependency: RegisterDependency


@dataclass(slots=True)
class RootWithUuid:
    request_id: uuid.UUID


def main() -> None:
    resolve_container = Container()
    resolved = resolve_container.resolve(AutoregRoot)
    autoregister_chain = isinstance(resolved.branch.leaf, AutoregLeaf)
    print(f"autoregister_chain={autoregister_chain}")  # => autoregister_chain=True

    register_container = Container(autoregister_dependencies=False)
    register_container.add_concrete(
        RegisterRoot,
        autoregister_dependencies=True,
    )
    try:
        resolved_register_root = register_container.resolve(RegisterRoot)
    except DIWireDependencyNotRegisteredError:
        autoregister_deps_on_register = False
    else:
        autoregister_deps_on_register = isinstance(
            resolved_register_root.dependency,
            RegisterDependency,
        )
    print(
        f"autoregister_deps_on_register={autoregister_deps_on_register}",
    )  # => autoregister_deps_on_register=True

    strict_container = Container(autoregister_concrete_types=False)
    try:
        strict_container.resolve(StrictRoot)
    except DIWireDependencyNotRegisteredError as error:
        strict_missing = type(error).__name__
    print(
        f"strict_missing={strict_missing}",
    )  # => strict_missing=DIWireDependencyNotRegisteredError

    uuid_container = Container()
    try:
        uuid_container.resolve(RootWithUuid)
    except DIWireDependencyNotRegisteredError:
        skipped_before_registration = True
    else:
        skipped_before_registration = False

    expected_uuid = uuid.UUID(int=0)
    uuid_container.add_instance(expected_uuid)
    resolved_uuid = uuid_container.resolve(RootWithUuid)
    uuid_skipped_until_registered = (
        skipped_before_registration and resolved_uuid.request_id is expected_uuid
    )
    print(
        f"uuid_skipped_until_registered={uuid_skipped_until_registered}",
    )  # => uuid_skipped_until_registered=True


if __name__ == "__main__":
    main()
```

<a id="ex-09-autoregistration--02-resolve-chain-py"></a>
### 02_resolve_chain.py ([ex_09_autoregistration/02_resolve_chain.py](ex_09_autoregistration/02_resolve_chain.py))

Focused example: resolve-time autoregistration of a dependency chain.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class Leaf:
    pass


@dataclass(slots=True)
class Branch:
    leaf: Leaf


@dataclass(slots=True)
class Root:
    branch: Branch


def main() -> None:
    container = Container()
    resolved = container.resolve(Root)
    print(
        f"autoregister_chain={isinstance(resolved.branch.leaf, Leaf)}",
    )  # => autoregister_chain=True


if __name__ == "__main__":
    main()
```

<a id="ex-09-autoregistration--03-add-dependency-autoregister-py"></a>
### 03_add_dependency_autoregister.py ([ex_09_autoregistration/03_add_dependency_autoregister.py](ex_09_autoregistration/03_add_dependency_autoregister.py))

Focused example: registration-time dependency autoregistration.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


class Dependency:
    pass


@dataclass(slots=True)
class Root:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_dependencies=False)
    container.add_concrete(Root, autoregister_dependencies=True)

    resolved = container.resolve(Root)
    autoregistered = isinstance(resolved.dependency, Dependency)
    print(
        f"autoregister_deps_on_register={autoregistered}",
    )  # => autoregister_deps_on_register=True


if __name__ == "__main__":
    main()
```

<a id="ex-09-autoregistration--04-strict-mode-py"></a>
### 04_strict_mode.py ([ex_09_autoregistration/04_strict_mode.py](ex_09_autoregistration/04_strict_mode.py))

Focused example: strict mode without concrete autoregistration.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError


class Dependency:
    pass


@dataclass(slots=True)
class Root:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    try:
        container.resolve(Root)
    except DIWireDependencyNotRegisteredError as error:
        error_name = type(error).__name__

    print(f"strict_missing={error_name}")  # => strict_missing=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
```

<a id="ex-09-autoregistration--05-uuid-special-type-py"></a>
### 05_uuid_special_type.py ([ex_09_autoregistration/05_uuid_special_type.py](ex_09_autoregistration/05_uuid_special_type.py))

Focused example: ``uuid.UUID`` requires explicit registration.

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass

from diwire import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError


@dataclass(slots=True)
class Root:
    request_id: uuid.UUID


def main() -> None:
    container = Container()

    try:
        container.resolve(Root)
    except DIWireDependencyNotRegisteredError:
        skipped_before_registration = True
    else:
        skipped_before_registration = False

    expected_uuid = uuid.UUID(int=0)
    container.add_instance(expected_uuid)
    resolved = container.resolve(Root)

    print(
        f"uuid_skipped_until_registered={skipped_before_registration and resolved.request_id is expected_uuid}",
    )  # => uuid_skipped_until_registered=True


if __name__ == "__main__":
    main()
```

<a id="ex-10-provider-context"></a>
## 10. Provider Context

Files:
- [01_provider_context.py](#ex-10-provider-context--01-provider-context-py)
- [02_unbound_error.py](#ex-10-provider-context--02-unbound-error-py)
- [03_bound_resolution.py](#ex-10-provider-context--03-bound-resolution-py)
- [04_inject_wrappers.py](#ex-10-provider-context--04-inject-wrappers-py)
- [05_use_provider_context_false.py](#ex-10-provider-context--05-use-provider-context-false-py)

<a id="ex-10-provider-context--01-provider-context-py"></a>
### 01_provider_context.py ([ex_10_provider_context/01_provider_context.py](ex_10_provider_context/01_provider_context.py))

ProviderContext: unbound errors, fallback resolution/scope/injection, and bound precedence.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, ProviderContext, Scope
from diwire.exceptions import DIWireProviderNotSetError


@dataclass(slots=True)
class Message:
    value: str


def main() -> None:
    context = ProviderContext()

    try:
        context.resolve(Message)
    except DIWireProviderNotSetError as error:
        print(f"unbound_error={type(error).__name__}")  # => unbound_error=DIWireProviderNotSetError

    first = Container(provider_context=context, autoregister_concrete_types=False)
    first.add_instance(Message("first"), provides=Message)

    second = Container(provider_context=context, autoregister_concrete_types=False)
    second.add_instance(Message("second"), provides=Message)

    print(
        f"fallback_resolve={context.resolve(Message).value == 'second'}"
    )  # => fallback_resolve=True
    with context.enter_scope(Scope.REQUEST) as request_scope:
        print(
            f"fallback_enter_scope={request_scope.resolve(Message).value == 'second'}"
        )  # => fallback_enter_scope=True

    @context.inject
    def read_message(message: Injected[Message]) -> str:
        return message.value

    print(f"fallback_last_wins={read_message() == 'second'}")  # => fallback_last_wins=True

    with first.compile():
        print(f"bound_precedence={read_message() == 'first'}")  # => bound_precedence=True


if __name__ == "__main__":
    main()
```

<a id="ex-10-provider-context--02-unbound-error-py"></a>
### 02_unbound_error.py ([ex_10_provider_context/02_unbound_error.py](ex_10_provider_context/02_unbound_error.py))

Focused example: unbound ``ProviderContext`` usage error.

```python
from __future__ import annotations

from diwire import ProviderContext
from diwire.exceptions import DIWireProviderNotSetError


def main() -> None:
    context = ProviderContext()

    try:
        context.resolve(str)
    except DIWireProviderNotSetError as error:
        print(f"unbound_error={type(error).__name__}")  # => unbound_error=DIWireProviderNotSetError


if __name__ == "__main__":
    main()
```

<a id="ex-10-provider-context--03-bound-resolution-py"></a>
### 03_bound_resolution.py ([ex_10_provider_context/03_bound_resolution.py](ex_10_provider_context/03_bound_resolution.py))

Focused example: bound resolver resolution through ProviderContext.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, ProviderContext


@dataclass(slots=True)
class Service:
    value: str


def main() -> None:
    context = ProviderContext()
    container = Container(provider_context=context, autoregister_concrete_types=False)
    container.add_instance(Service("bound"), provides=Service)

    with container.compile():
        resolved = context.resolve(Service)
        print(f"bound_resolve_ok={resolved.value == 'bound'}")  # => bound_resolve_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-10-provider-context--04-inject-wrappers-py"></a>
### 04_inject_wrappers.py ([ex_10_provider_context/04_inject_wrappers.py](ex_10_provider_context/04_inject_wrappers.py))

Focused example: ``@provider_context.inject`` on function and method.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container, Injected, provider_context


@dataclass(slots=True)
class Message:
    value: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance(Message(value="context-message"), provides=Message)

    @provider_context.inject
    def read_function(message: Injected[Message]) -> str:
        return message.value

    class Handler:
        @provider_context.inject
        def read_method(self, message: Injected[Message]) -> str:
            return message.value

    handler = Handler()

    print(
        f"inject_function_ok={read_function() == 'context-message'}"
    )  # => inject_function_ok=True
    print(
        f"inject_method_ok={handler.read_method() == 'context-message'}"
    )  # => inject_method_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-10-provider-context--05-use-provider-context-false-py"></a>
### 05_use_provider_context_false.py ([ex_10_provider_context/05_use_provider_context_false.py](ex_10_provider_context/05_use_provider_context_false.py))

Focused example: strict-mode entrypoint rebind with use_provider_context=False.

```python
from __future__ import annotations

from diwire import Container


def _bound_self(method: object) -> object | None:
    return getattr(method, "__self__", None)


def main() -> None:
    container = Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=False,
        use_provider_context=False,
    )
    container.add_instance("legacy", provides=str)

    compiled = container.compile()
    print(f"rebind_enabled={_bound_self(container.resolve) is compiled}")  # => rebind_enabled=True


if __name__ == "__main__":
    main()
```

<a id="ex-11-lock-modes"></a>
## 11. Lock Modes

Files:
- [01_lock_modes.py](#ex-11-lock-modes--01-lock-modes-py)

<a id="ex-11-lock-modes--01-lock-modes-py"></a>
### 01_lock_modes.py ([ex_11_lock_modes/01_lock_modes.py](ex_11_lock_modes/01_lock_modes.py))

Lock mode defaults and per-provider overrides.

This module demonstrates lock behavior for cached root-scoped (singleton) providers:

1. Default ``lock_mode="auto"`` uses thread locks for sync-only graphs.
2. Container-level ``lock_mode=LockMode.NONE`` disables locking.
3. Provider-level ``lock_mode`` can override the container setting.

```python
from __future__ import annotations

import threading
import time

from diwire import Container, Lifetime, LockMode


class DefaultLockService:
    pass


class ContainerLockService:
    pass


class OverrideLockService:
    pass


def _singleton_two_thread_stats(
    *,
    container: Container,
    provides: type[object],
    lock_mode: LockMode | None = None,
) -> tuple[int, bool]:
    calls = 0
    calls_lock = threading.Lock()
    factory_started = threading.Event()
    factory_release = threading.Event()
    results: list[object | None] = [None, None]

    def factory() -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
            factory_started.set()
        factory_release.wait(timeout=2.0)
        return provides()

    if lock_mode is None:
        container.add_factory(
            factory,
            provides=provides,
            lifetime=Lifetime.SCOPED,
        )
    else:
        container.add_factory(
            factory,
            provides=provides,
            lifetime=Lifetime.SCOPED,
            lock_mode=lock_mode,
        )

    resolver = container.compile()

    def worker(index: int) -> None:
        results[index] = resolver.resolve(provides)

    thread_0 = threading.Thread(target=worker, args=(0,))
    thread_0.start()

    if not factory_started.wait(timeout=2.0):
        msg = "Factory was not called within timeout."
        raise RuntimeError(msg)

    thread_1 = threading.Thread(target=worker, args=(1,))
    thread_1.start()

    deadline = time.monotonic() + 0.5
    while True:
        with calls_lock:
            current_calls = calls
        if current_calls >= 2 or time.monotonic() >= deadline:
            break
        time.sleep(0.001)

    factory_release.set()

    for thread in (thread_0, thread_1):
        thread.join(timeout=2.0)
        if thread.is_alive():
            msg = "Worker thread did not finish within timeout."
            raise RuntimeError(msg)

    if results[0] is None or results[1] is None:
        msg = "Worker threads did not store resolution results."
        raise RuntimeError(msg)

    with calls_lock:
        total_calls = calls

    shared = results[0] is results[1]
    return total_calls, shared


def main() -> None:
    default_calls, default_shared = _singleton_two_thread_stats(
        container=Container(),
        provides=DefaultLockService,
    )
    print(
        f"default_auto=calls={default_calls} shared={default_shared}",
    )  # => default_auto=calls=1 shared=True

    none_calls, none_shared = _singleton_two_thread_stats(
        container=Container(lock_mode=LockMode.NONE),
        provides=ContainerLockService,
    )
    print(
        f"container_none=calls={none_calls} shared={none_shared}",
    )  # => container_none=calls=2 shared=False

    override_calls, override_shared = _singleton_two_thread_stats(
        container=Container(lock_mode=LockMode.NONE),
        provides=OverrideLockService,
        lock_mode=LockMode.THREAD,
    )
    print(
        f"override_thread=calls={override_calls} shared={override_shared}",
    )  # => override_thread=calls=1 shared=True


if __name__ == "__main__":
    main()
```

<a id="ex-12-supported-frameworks"></a>
## 12. Supported Frameworks

Files:
- [01_supported_frameworks.py](#ex-12-supported-frameworks--01-supported-frameworks-py)
- [02_dataclass.py](#ex-12-supported-frameworks--02-dataclass-py)
- [03_namedtuple.py](#ex-12-supported-frameworks--03-namedtuple-py)
- [04_attrs.py](#ex-12-supported-frameworks--04-attrs-py)
- [05_pydantic.py](#ex-12-supported-frameworks--05-pydantic-py)
- [06_msgspec.py](#ex-12-supported-frameworks--06-msgspec-py)

<a id="ex-12-supported-frameworks--01-supported-frameworks-py"></a>
### 01_supported_frameworks.py ([ex_12_supported_frameworks/01_supported_frameworks.py](ex_12_supported_frameworks/01_supported_frameworks.py))

Supported framework constructors/fields for dependency extraction.

This module demonstrates constructor/field extraction for:

1. ``dataclasses``
2. ``NamedTuple``
3. ``attrs.define``
4. ``pydantic.BaseModel`` (v2)
5. ``msgspec.Struct``

A single shared dependency instance is registered and each framework-backed
consumer resolves it through explicit concrete registrations.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import attrs
import msgspec
import pydantic

from diwire import Container


@dataclass(slots=True)
class FrameworkDependency:
    name: str


@dataclass(slots=True)
class DataclassConsumer:
    dependency: FrameworkDependency


class NamedTupleConsumer(NamedTuple):
    dependency: FrameworkDependency


@attrs.define
class AttrsConsumer:
    dependency: FrameworkDependency


class PydanticConsumer(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    dependency: FrameworkDependency


class MsgspecConsumer(msgspec.Struct):
    dependency: FrameworkDependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = FrameworkDependency(name="framework")
    container.add_instance(dependency)

    container.add_concrete(DataclassConsumer)
    container.add_concrete(NamedTupleConsumer)
    container.add_concrete(AttrsConsumer)
    container.add_concrete(PydanticConsumer)
    container.add_concrete(MsgspecConsumer)

    dataclass_ok = container.resolve(DataclassConsumer).dependency is dependency
    namedtuple_ok = container.resolve(NamedTupleConsumer).dependency is dependency
    attrs_ok = container.resolve(AttrsConsumer).dependency is dependency
    pydantic_ok = container.resolve(PydanticConsumer).dependency is dependency
    msgspec_ok = container.resolve(MsgspecConsumer).dependency is dependency

    print(f"dataclass_ok={dataclass_ok}")  # => dataclass_ok=True
    print(f"namedtuple_ok={namedtuple_ok}")  # => namedtuple_ok=True
    print(f"attrs_ok={attrs_ok}")  # => attrs_ok=True
    print(f"pydantic_ok={pydantic_ok}")  # => pydantic_ok=True
    print(f"msgspec_ok={msgspec_ok}")  # => msgspec_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-12-supported-frameworks--02-dataclass-py"></a>
### 02_dataclass.py ([ex_12_supported_frameworks/02_dataclass.py](ex_12_supported_frameworks/02_dataclass.py))

Focused example: dataclass constructor dependency extraction.

```python
from __future__ import annotations

from dataclasses import dataclass

from diwire import Container


@dataclass(slots=True)
class Dependency:
    name: str


@dataclass(slots=True)
class Consumer:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency(name="framework")
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(
        f"dataclass_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => dataclass_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-12-supported-frameworks--03-namedtuple-py"></a>
### 03_namedtuple.py ([ex_12_supported_frameworks/03_namedtuple.py](ex_12_supported_frameworks/03_namedtuple.py))

Focused example: ``NamedTuple`` dependency extraction.

```python
from __future__ import annotations

from typing import NamedTuple

from diwire import Container


class Dependency:
    pass


class Consumer(NamedTuple):
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(
        f"namedtuple_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => namedtuple_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-12-supported-frameworks--04-attrs-py"></a>
### 04_attrs.py ([ex_12_supported_frameworks/04_attrs.py](ex_12_supported_frameworks/04_attrs.py))

Focused example: ``attrs.define`` dependency extraction.

```python
from __future__ import annotations

import attrs

from diwire import Container


class Dependency:
    pass


@attrs.define
class Consumer:
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(f"attrs_ok={container.resolve(Consumer).dependency is dependency}")  # => attrs_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-12-supported-frameworks--05-pydantic-py"></a>
### 05_pydantic.py ([ex_12_supported_frameworks/05_pydantic.py](ex_12_supported_frameworks/05_pydantic.py))

Focused example: pydantic v2 model field dependency extraction.

```python
from __future__ import annotations

import pydantic

from diwire import Container


class Dependency:
    pass


class Consumer(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(
        f"pydantic_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => pydantic_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-12-supported-frameworks--06-msgspec-py"></a>
### 06_msgspec.py ([ex_12_supported_frameworks/06_msgspec.py](ex_12_supported_frameworks/06_msgspec.py))

Focused example: ``msgspec.Struct`` field dependency extraction.

```python
from __future__ import annotations

import msgspec

from diwire import Container


class Dependency:
    pass


class Consumer(msgspec.Struct):
    dependency: Dependency


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    dependency = Dependency()
    container.add_instance(dependency)
    container.add_concrete(Consumer)

    print(
        f"msgspec_ok={container.resolve(Consumer).dependency is dependency}",
    )  # => msgspec_ok=True


if __name__ == "__main__":
    main()
```

<a id="ex-13-pydantic-settings"></a>
## 13. Pydantic Settings

Files:
- [01_pydantic_settings.py](#ex-13-pydantic-settings--01-pydantic-settings-py)

<a id="ex-13-pydantic-settings--01-pydantic-settings-py"></a>
### 01_pydantic_settings.py ([ex_13_pydantic_settings/01_pydantic_settings.py](ex_13_pydantic_settings/01_pydantic_settings.py))

Pydantic settings auto-registration.

``BaseSettings`` subclasses are auto-registered by diwire as root-scope
singleton factories. Resolving the same settings type repeatedly returns the
same object instance.

```python
from __future__ import annotations

from pydantic_settings import BaseSettings

from diwire import Container


class AppSettings(BaseSettings):
    value: str = "settings"


def main() -> None:
    container = Container()

    first = container.resolve(AppSettings)
    second = container.resolve(AppSettings)

    print(f"settings_singleton={first is second}")  # => settings_singleton=True
    print(f"settings_value={first.value}")  # => settings_value=settings


if __name__ == "__main__":
    main()
```

<a id="ex-14-pytest-plugin"></a>
## 14. Pytest Plugin

Files:
- [01_pytest_plugin.py](#ex-14-pytest-plugin--01-pytest-plugin-py)
- [test_demo.py](#ex-14-pytest-plugin--test-demo-py)

<a id="ex-14-pytest-plugin--01-pytest-plugin-py"></a>
### 01_pytest_plugin.py ([ex_14_pytest_plugin/01_pytest_plugin.py](ex_14_pytest_plugin/01_pytest_plugin.py))

Pytest plugin integration smoke test.

Runs ``pytest -q test_demo.py`` in this folder to validate
``diwire.integrations.pytest_plugin`` with ``Injected[T]`` test parameters.

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    example_dir = Path(__file__).resolve().parent
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "test_demo.py"],
        cwd=example_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"exit_code={completed.returncode}")  # => exit_code=0


if __name__ == "__main__":
    main()
```

<a id="ex-14-pytest-plugin--test-demo-py"></a>
### test_demo.py ([ex_14_pytest_plugin/test_demo.py](ex_14_pytest_plugin/test_demo.py))

```python
from __future__ import annotations

import pytest

from diwire import Container, Injected, Lifetime

pytest_plugins = ["diwire.integrations.pytest_plugin"]


class Service:
    pass


class ServiceImpl(Service):
    pass


@pytest.fixture()
def diwire_container() -> Container:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        ServiceImpl,
        provides=Service,
        lifetime=Lifetime.SCOPED,
    )
    return container


def test_plugin_injects_parameters(service: Injected[Service]) -> None:
    if not isinstance(service, ServiceImpl):
        msg = "Injected service is not ServiceImpl"
        raise TypeError(msg)
```

<a id="ex-15-fastapi"></a>
## 15. FastAPI

Files:
- [01_fastapi.py](#ex-15-fastapi--01-fastapi-py)

<a id="ex-15-fastapi--01-fastapi-py"></a>
### 01_fastapi.py ([ex_15_fastapi/01_fastapi.py](ex_15_fastapi/01_fastapi.py))

FastAPI integration via ``@provider_context.inject(scope=Scope.REQUEST)``.

This module demonstrates request-scoped injection without network startup:

1. A FastAPI route function decorated with ``@provider_context.inject``.
2. A request-scoped generator resource that increments open/close counters.
3. Two in-process calls through ``TestClient``.

```python
from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diwire import Container, Injected, Lifetime, Scope, provider_context


@dataclass(slots=True)
class RequestResource:
    label: str


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    app = FastAPI()
    lifecycle = {"opened": 0, "closed": 0}

    def provide_resource() -> Generator[RequestResource, None, None]:
        lifecycle["opened"] += 1
        resource = RequestResource(label=f"req-{lifecycle['opened']}")
        try:
            yield resource
        finally:
            lifecycle["closed"] += 1

    container.add_generator(
        provide_resource,
        provides=RequestResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    @app.get("/resource/{item_id}")
    @provider_context.inject(scope=Scope.REQUEST)
    def get_resource(item_id: int, resource: Injected[RequestResource]) -> dict[str, int | str]:
        return {"id": item_id, "resource": resource.label}

    client = TestClient(app)
    response_1 = client.get("/resource/1").json()
    response_2 = client.get("/resource/2").json()

    response_1_json = json.dumps(response_1, sort_keys=True, separators=(",", ":"))
    response_2_json = json.dumps(response_2, sort_keys=True, separators=(",", ":"))
    cleanup_json = json.dumps(lifecycle, sort_keys=True, separators=(",", ":"))

    print(f"response_1={response_1_json}")  # => response_1={"id":1,"resource":"req-1"}
    print(f"response_2={response_2_json}")  # => response_2={"id":2,"resource":"req-2"}
    print(f"cleanup={cleanup_json}")  # => cleanup={"closed":2,"opened":2}


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting"></a>
## 16. Errors and Troubleshooting

Files:
- [01_errors_and_troubleshooting.py](#ex-16-errors-and-troubleshooting--01-errors-and-troubleshooting-py)
- [02_missing_dependency_error.py](#ex-16-errors-and-troubleshooting--02-missing-dependency-error-py)
- [03_scope_mismatch_error.py](#ex-16-errors-and-troubleshooting--03-scope-mismatch-error-py)
- [04_async_in_sync_error.py](#ex-16-errors-and-troubleshooting--04-async-in-sync-error-py)
- [05_inference_error.py](#ex-16-errors-and-troubleshooting--05-inference-error-py)
- [06_generic_error.py](#ex-16-errors-and-troubleshooting--06-generic-error-py)
- [07_invalid_registration_error.py](#ex-16-errors-and-troubleshooting--07-invalid-registration-error-py)

<a id="ex-16-errors-and-troubleshooting--01-errors-and-troubleshooting-py"></a>
### 01_errors_and_troubleshooting.py ([ex_16_errors_and_troubleshooting/01_errors_and_troubleshooting.py](ex_16_errors_and_troubleshooting/01_errors_and_troubleshooting.py))

Common error classes for troubleshooting.

This module triggers representative error paths and prints exception type names
so you can recognize each error category quickly.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container, Scope
from diwire.exceptions import (
    DIWireAsyncDependencyInSyncContextError,
    DIWireDependencyNotRegisteredError,
    DIWireInvalidGenericTypeArgumentError,
    DIWireInvalidRegistrationError,
    DIWireProviderDependencyInferenceError,
    DIWireScopeMismatchError,
)


class MissingDependency:
    pass


class RequestScopedDependency:
    pass


class AsyncDependency:
    pass


class TypedDependency:
    pass


class Model:
    pass


M = TypeVar("M", bound=Model)


class ModelBox(Generic[M]):
    pass


@dataclass(slots=True)
class DefaultModelBox(ModelBox[M]):
    type_arg: type[M]


def main() -> None:
    missing_container = Container(autoregister_concrete_types=False)
    try:
        missing_container.resolve(MissingDependency)
    except DIWireDependencyNotRegisteredError as error:
        missing = type(error).__name__
    print(f"missing={missing}")  # => missing=DIWireDependencyNotRegisteredError

    scope_container = Container(autoregister_concrete_types=False)
    scope_container.add_concrete(
        RequestScopedDependency,
        provides=RequestScopedDependency,
        scope=Scope.REQUEST,
    )
    try:
        scope_container.resolve(RequestScopedDependency)
    except DIWireScopeMismatchError as error:
        scope = type(error).__name__
    print(f"scope={scope}")  # => scope=DIWireScopeMismatchError

    async_container = Container(autoregister_concrete_types=False)

    async def build_async_dependency() -> AsyncDependency:
        return AsyncDependency()

    async_container.add_factory(build_async_dependency, provides=AsyncDependency)
    try:
        async_container.resolve(AsyncDependency)
    except DIWireAsyncDependencyInSyncContextError as error:
        async_in_sync = type(error).__name__
    print(
        f"async_in_sync={async_in_sync}",
    )  # => async_in_sync=DIWireAsyncDependencyInSyncContextError

    inference_container = Container(autoregister_concrete_types=False)

    def build_typed_dependency(raw_value) -> TypedDependency:  # type: ignore[no-untyped-def]
        _ = raw_value
        return TypedDependency()

    try:
        inference_container.add_factory(build_typed_dependency, provides=TypedDependency)
    except DIWireProviderDependencyInferenceError as error:
        inference = type(error).__name__
    print(f"inference={inference}")  # => inference=DIWireProviderDependencyInferenceError

    generic_container = Container(autoregister_concrete_types=False)
    generic_container.add_concrete(DefaultModelBox, provides=ModelBox)
    invalid_key = cast("Any", ModelBox)[str]
    try:
        generic_container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError as error:
        generic = type(error).__name__
    print(f"generic={generic}")  # => generic=DIWireInvalidGenericTypeArgumentError

    invalid_registration_container = Container()
    try:
        invalid_registration_container.add_instance(
            provides=cast("Any", None),
            instance=object(),
        )
    except DIWireInvalidRegistrationError as error:
        invalid_reg = type(error).__name__
    print(f"invalid_reg={invalid_reg}")  # => invalid_reg=DIWireInvalidRegistrationError


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting--02-missing-dependency-error-py"></a>
### 02_missing_dependency_error.py ([ex_16_errors_and_troubleshooting/02_missing_dependency_error.py](ex_16_errors_and_troubleshooting/02_missing_dependency_error.py))

Focused example: ``DIWireDependencyNotRegisteredError``.

```python
from __future__ import annotations

from diwire import Container
from diwire.exceptions import DIWireDependencyNotRegisteredError


class MissingDependency:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    try:
        container.resolve(MissingDependency)
    except DIWireDependencyNotRegisteredError as error:
        error_name = type(error).__name__

    print(f"missing={error_name}")  # => missing=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting--03-scope-mismatch-error-py"></a>
### 03_scope_mismatch_error.py ([ex_16_errors_and_troubleshooting/03_scope_mismatch_error.py](ex_16_errors_and_troubleshooting/03_scope_mismatch_error.py))

Focused example: ``DIWireScopeMismatchError``.

```python
from __future__ import annotations

from diwire import Container, Scope
from diwire.exceptions import DIWireScopeMismatchError


class RequestDependency:
    pass


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        RequestDependency,
        provides=RequestDependency,
        scope=Scope.REQUEST,
    )

    try:
        container.resolve(RequestDependency)
    except DIWireScopeMismatchError as error:
        error_name = type(error).__name__

    print(f"scope={error_name}")  # => scope=DIWireScopeMismatchError


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting--04-async-in-sync-error-py"></a>
### 04_async_in_sync_error.py ([ex_16_errors_and_troubleshooting/04_async_in_sync_error.py](ex_16_errors_and_troubleshooting/04_async_in_sync_error.py))

Focused example: ``DIWireAsyncDependencyInSyncContextError``.

```python
from __future__ import annotations

from diwire import Container
from diwire.exceptions import DIWireAsyncDependencyInSyncContextError


class AsyncDependency:
    pass


async def provide_async_dependency() -> AsyncDependency:
    return AsyncDependency()


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(provide_async_dependency, provides=AsyncDependency)

    try:
        container.resolve(AsyncDependency)
    except DIWireAsyncDependencyInSyncContextError as error:
        error_name = type(error).__name__

    print(f"async_in_sync={error_name}")  # => async_in_sync=DIWireAsyncDependencyInSyncContextError


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting--05-inference-error-py"></a>
### 05_inference_error.py ([ex_16_errors_and_troubleshooting/05_inference_error.py](ex_16_errors_and_troubleshooting/05_inference_error.py))

Focused example: ``DIWireProviderDependencyInferenceError``.

```python
from __future__ import annotations

from diwire import Container
from diwire.exceptions import DIWireProviderDependencyInferenceError


class Service:
    pass


def build_service(raw_value) -> Service:  # type: ignore[no-untyped-def]
    _ = raw_value
    return Service()


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    try:
        container.add_factory(build_service, provides=Service)
    except DIWireProviderDependencyInferenceError as error:
        error_name = type(error).__name__

    print(f"inference={error_name}")  # => inference=DIWireProviderDependencyInferenceError


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting--06-generic-error-py"></a>
### 06_generic_error.py ([ex_16_errors_and_troubleshooting/06_generic_error.py](ex_16_errors_and_troubleshooting/06_generic_error.py))

Focused example: ``DIWireInvalidGenericTypeArgumentError``.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from diwire import Container
from diwire.exceptions import DIWireInvalidGenericTypeArgumentError


class Model:
    pass


M = TypeVar("M", bound=Model)


class ModelBox(Generic[M]):
    pass


@dataclass(slots=True)
class DefaultModelBox(ModelBox[M]):
    type_arg: type[M]


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(DefaultModelBox, provides=ModelBox)

    invalid_key = cast("Any", ModelBox)[str]
    try:
        container.resolve(invalid_key)
    except DIWireInvalidGenericTypeArgumentError as error:
        error_name = type(error).__name__

    print(f"generic={error_name}")  # => generic=DIWireInvalidGenericTypeArgumentError


if __name__ == "__main__":
    main()
```

<a id="ex-16-errors-and-troubleshooting--07-invalid-registration-error-py"></a>
### 07_invalid_registration_error.py ([ex_16_errors_and_troubleshooting/07_invalid_registration_error.py](ex_16_errors_and_troubleshooting/07_invalid_registration_error.py))

Focused example: ``DIWireInvalidRegistrationError``.

```python
from __future__ import annotations

from typing import Any, cast

from diwire import Container
from diwire.exceptions import DIWireInvalidRegistrationError


def main() -> None:
    container = Container()

    try:
        container.add_instance(object(), provides=cast("Any", None))
    except DIWireInvalidRegistrationError as error:
        error_name = type(error).__name__

    print(f"invalid_reg={error_name}")  # => invalid_reg=DIWireInvalidRegistrationError


if __name__ == "__main__":
    main()
```

<a id="ex-17-scope-context-values"></a>
## 17. Scope Context Values

Files:
- [01_scope_context_values.py](#ex-17-scope-context-values--01-scope-context-values-py)
- [02_injected_callable_context.py](#ex-17-scope-context-values--02-injected-callable-context-py)
- [03_annotated_context_keys.py](#ex-17-scope-context-values--03-annotated-context-keys-py)
- [04_context_without_scope_open.py](#ex-17-scope-context-values--04-context-without-scope-open-py)

<a id="ex-17-scope-context-values--01-scope-context-values-py"></a>
### 01_scope_context_values.py ([ex_17_scope_context_values/01_scope_context_values.py](ex_17_scope_context_values/01_scope_context_values.py))

Scope context values with FromContext[T].

This topic demonstrates:

1. Provider dependencies that read values from scope context.
2. Parent-to-child context visibility across nested scopes.
3. Child-scope override behavior for the same context key.
4. Direct resolver access via ``resolve(FromContext[T])``.
5. Missing context failure mode.

```python
from __future__ import annotations

from diwire import Container, FromContext, Lifetime, Scope
from diwire.exceptions import DIWireDependencyNotRegisteredError


class RequestValue:
    def __init__(self, value: int) -> None:
        self.value = value


class ActionValue:
    def __init__(self, value: int) -> None:
        self.value = value


class StepValue:
    def __init__(self, value: int) -> None:
        self.value = value


def build_request_value(value: FromContext[int]) -> RequestValue:
    return RequestValue(value=value)


def build_action_value(value: FromContext[int]) -> ActionValue:
    return ActionValue(value=value)


def build_step_value(value: FromContext[int]) -> StepValue:
    return StepValue(value=value)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(
        build_request_value,
        provides=RequestValue,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_factory(
        build_action_value,
        provides=ActionValue,
        scope=Scope.ACTION,
        lifetime=Lifetime.TRANSIENT,
    )
    container.add_factory(
        build_step_value,
        provides=StepValue,
        scope=Scope.STEP,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope(Scope.REQUEST, context={int: 1}) as request_scope:
        request_value = request_scope.resolve(RequestValue).value
        with request_scope.enter_scope(Scope.ACTION) as action_scope:
            action_value = action_scope.resolve(ActionValue).value
            with action_scope.enter_scope(Scope.STEP, context={int: 2}) as step_scope:
                step_value = step_scope.resolve(StepValue).value
                request_value_from_step = step_scope.resolve(RequestValue).value
                direct_context = step_scope.resolve(FromContext[int])

    with container.enter_scope(Scope.REQUEST) as request_scope_without_context:
        try:
            request_scope_without_context.resolve(RequestValue)
        except DIWireDependencyNotRegisteredError as error:
            missing_context_error = type(error).__name__

    print(f"request_value={request_value}")  # => request_value=1
    print(f"action_inherits_parent={action_value}")  # => action_inherits_parent=1
    print(f"step_overrides_parent={step_value}")  # => step_overrides_parent=2
    print(f"request_stays_parent={request_value_from_step}")  # => request_stays_parent=1
    print(f"direct_from_context={direct_context}")  # => direct_from_context=2
    print(
        f"missing_context_error={missing_context_error}",
    )  # => missing_context_error=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
```

<a id="ex-17-scope-context-values--02-injected-callable-context-py"></a>
### 02_injected_callable_context.py ([ex_17_scope_context_values/02_injected_callable_context.py](ex_17_scope_context_values/02_injected_callable_context.py))

Injected callables can consume FromContext values via diwire_context.

```python
from __future__ import annotations

from diwire import Container, FromContext, Scope, provider_context


def main() -> None:
    Container(autoregister_concrete_types=False)

    @provider_context.inject(scope=Scope.REQUEST)
    def handler(value: FromContext[int]) -> int:
        return value

    from_context = handler(diwire_context={int: 7})
    overridden = handler(value=8)

    print(f"from_context={from_context}")
    print(f"overridden={overridden}")


if __name__ == "__main__":
    main()
```

<a id="ex-17-scope-context-values--03-annotated-context-keys-py"></a>
### 03_annotated_context_keys.py ([ex_17_scope_context_values/03_annotated_context_keys.py](ex_17_scope_context_values/03_annotated_context_keys.py))

Annotated tokens can be used as scope context keys.

```python
from __future__ import annotations

from typing import Annotated, TypeAlias

from diwire import Component, Container, FromContext, Lifetime, Scope

ReplicaNumber: TypeAlias = Annotated[int, Component("replica")]


class ReplicaConsumer:
    def __init__(self, value: int) -> None:
        self.value = value


def build_consumer(value: FromContext[ReplicaNumber]) -> ReplicaConsumer:
    return ReplicaConsumer(value=value)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(
        build_consumer,
        provides=ReplicaConsumer,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope(Scope.REQUEST, context={ReplicaNumber: 42}) as request_scope:
        resolved = request_scope.resolve(ReplicaConsumer)
        direct = request_scope.resolve(FromContext[ReplicaNumber])

    print(f"consumer_value={resolved.value}")
    print(f"direct_value={direct}")


if __name__ == "__main__":
    main()
```

<a id="ex-17-scope-context-values--04-context-without-scope-open-py"></a>
### 04_context_without_scope_open.py ([ex_17_scope_context_values/04_context_without_scope_open.py](ex_17_scope_context_values/04_context_without_scope_open.py))

Passing diwire_context without opening a scope raises a clear error.

```python
from __future__ import annotations

from diwire import Container, FromContext, provider_context
from diwire.exceptions import DIWireInvalidRegistrationError


def main() -> None:
    Container(autoregister_concrete_types=False)

    @provider_context.inject(auto_open_scope=False)
    def handler(value: FromContext[int]) -> int:
        return value

    try:
        handler(diwire_context={int: 7})
    except DIWireInvalidRegistrationError as error:
        print(type(error).__name__)


if __name__ == "__main__":
    main()
```

<a id="ex-18-async"></a>
## 18. Async

Files:
- [01_async.py](#ex-18-async--01-async-py)

<a id="ex-18-async--01-async-py"></a>
### 01_async.py ([ex_18_async/01_async.py](ex_18_async/01_async.py))

Async factories, async cleanup, and async resolution.

This module demonstrates:

1. ``add_factory()`` with an ``async def`` factory + ``await container.aresolve(...)``.
2. ``add_generator()`` with an async generator + ``async with container.enter_scope(...)`` cleanup.
3. The sync/async boundary: resolving an async graph via ``resolve()`` raises an error.

```python
from __future__ import annotations

import asyncio

from diwire import Container, Lifetime, Scope
from diwire.exceptions import DIWireAsyncDependencyInSyncContextError


class AsyncService:
    def __init__(self, value: str) -> None:
        self.value = value


class AsyncResource:
    pass


async def main() -> None:
    container = Container(autoregister_concrete_types=False)

    async def build_async_service() -> AsyncService:
        await asyncio.sleep(0)
        return AsyncService(value="ok")

    container.add_factory(build_async_service, provides=AsyncService)

    service = await container.aresolve(AsyncService)
    print(f"async_factory_value={service.value}")  # => async_factory_value=ok

    try:
        container.resolve(AsyncService)
    except DIWireAsyncDependencyInSyncContextError as error:
        async_in_sync = type(error).__name__
    print(
        f"async_in_sync={async_in_sync}",
    )  # => async_in_sync=DIWireAsyncDependencyInSyncContextError

    state = {"opened": 0, "closed": 0}

    async def provide_async_resource():
        state["opened"] += 1
        try:
            yield AsyncResource()
        finally:
            await asyncio.sleep(0)
            state["closed"] += 1

    container.add_generator(
        provide_async_resource,
        provides=AsyncResource,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    async with container.enter_scope() as request_scope:
        _ = await request_scope.aresolve(AsyncResource)
        closed_before_exit = state["closed"]

    async_cleanup_after_exit = closed_before_exit == 0 and state["closed"] == 1
    print(
        f"async_cleanup_after_exit={async_cleanup_after_exit}",
    )  # => async_cleanup_after_exit=True


if __name__ == "__main__":
    asyncio.run(main())
```

<a id="ex-19-class-context-managers"></a>
## 19. Class Context Managers

Files:
- [01_class_context_managers.py](#ex-19-class-context-managers--01-class-context-managers-py)

<a id="ex-19-class-context-managers--01-class-context-managers-py"></a>
### 01_class_context_managers.py ([ex_19_class_context_managers/01_class_context_managers.py](ex_19_class_context_managers/01_class_context_managers.py))

Class-based context manager registration with inferred managed type.

This module demonstrates:

1. Registering a class context manager directly via ``add_context_manager(Service)``.
2. Inferring ``provides`` from ``Service.__enter__``.
3. Request-scoped caching behavior (same instance within one request scope).

```python
from __future__ import annotations

from types import TracebackType

from typing_extensions import Self

from diwire import Container, Lifetime, Scope


class Service:
    def __init__(self) -> None:
        print("new Service")  # => new Service

    def __enter__(self) -> Self:
        print("Entering Service context")  # => Entering Service context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        print("Exiting Service context")  # => Exiting Service context


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_context_manager(
        Service,
        scope=Scope.REQUEST,
        lifetime=Lifetime.SCOPED,
    )

    with container.enter_scope(Scope.REQUEST) as request_scope:
        service_1 = request_scope.resolve(Service)
        service_2 = request_scope.resolve(Service)
        same_instance = service_1 is service_2
    print(f"same_instance={same_instance}")  # => same_instance=True


if __name__ == "__main__":
    main()
```

<a id="ex-20-providers"></a>
## 20. Providers

Files:
- [01_providers.py](#ex-20-providers--01-providers-py)

<a id="ex-20-providers--01-providers-py"></a>
### 01_providers.py ([ex_20_providers/01_providers.py](ex_20_providers/01_providers.py))

Lazy providers with Provider[T].

This topic demonstrates:

1. Breaking a circular dependency with ``Provider[T]``.
2. Deferring expensive construction until the provider is called.
3. Preserving scoped vs transient lifetime semantics through provider calls.

```python
from __future__ import annotations

from diwire import Container, Lifetime, Provider, Scope


class A:
    def __init__(self, b_provider: Provider[B]) -> None:
        self._b_provider = b_provider

    def get_b(self) -> B:
        return self._b_provider()


class B:
    def __init__(self, a: A) -> None:
        self.a = a


class Expensive:
    build_count = 0

    def __init__(self) -> None:
        type(self).build_count += 1


class UsesExpensiveProvider:
    def __init__(self, expensive_provider: Provider[Expensive]) -> None:
        self._expensive_provider = expensive_provider

    def get_expensive(self) -> Expensive:
        return self._expensive_provider()


def _run_expensive_scenario(*, lifetime: Lifetime) -> tuple[int, int, bool]:
    Expensive.build_count = 0
    container = Container(autoregister_concrete_types=False)
    container.add_concrete(
        Expensive,
        provides=Expensive,
        scope=Scope.REQUEST,
        lifetime=lifetime,
    )
    container.add_concrete(
        UsesExpensiveProvider,
        provides=UsesExpensiveProvider,
        scope=Scope.REQUEST,
        lifetime=Lifetime.TRANSIENT,
    )

    with container.enter_scope() as request_scope:
        consumer = request_scope.resolve(UsesExpensiveProvider)
        before_calls = Expensive.build_count
        first = consumer.get_expensive()
        second = consumer.get_expensive()
        after_calls = Expensive.build_count
        same_identity = first is second
    return before_calls, after_calls, same_identity


def main() -> None:
    cycle_container = Container(autoregister_concrete_types=False)
    cycle_container.add_concrete(A)
    cycle_container.add_concrete(B)
    resolved_a = cycle_container.resolve(A)
    resolved_b = resolved_a.get_b()

    print(f"cycle_resolves={isinstance(resolved_b, B)}")  # => cycle_resolves=True
    print(f"cycle_same_a={resolved_b.a is resolved_a}")  # => cycle_same_a=True

    scoped_before, scoped_after, scoped_same = _run_expensive_scenario(
        lifetime=Lifetime.SCOPED,
    )
    print(f"scoped_before_call={scoped_before}")  # => scoped_before_call=0
    print(f"scoped_after_calls={scoped_after}")  # => scoped_after_calls=1
    print(f"scoped_same_identity={scoped_same}")  # => scoped_same_identity=True

    transient_before, transient_after, transient_same = _run_expensive_scenario(
        lifetime=Lifetime.TRANSIENT,
    )
    print(f"transient_before_call={transient_before}")  # => transient_before_call=0
    print(f"transient_after_calls={transient_after}")  # => transient_after_calls=2
    print(f"transient_same_identity={transient_same}")  # => transient_same_identity=False


if __name__ == "__main__":
    main()
```

<a id="ex-21-decorators"></a>
## 21. Decorators

Files:
- [01_decorators.py](#ex-21-decorators--01-decorators-py)
- [02_decorate_before_registration.py](#ex-21-decorators--02-decorate-before-registration-py)
- [03_open_generic_decorate.py](#ex-21-decorators--03-open-generic-decorate-py)

<a id="ex-21-decorators--01-decorators-py"></a>
### 01_decorators.py ([ex_21_decorators/01_decorators.py](ex_21_decorators/01_decorators.py))

Decorators: the easiest mental model.

Read this file top-to-bottom in three steps:

1. Register a base service (``Greeter`` -> ``SimpleGreeter``).
2. Add decorators; each new call becomes the new outer layer.
3. Re-register the base service; decorators stay in place automatically.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from diwire import Container


class Greeter(Protocol):
    def greet(self, name: str) -> str: ...


class SimpleGreeter:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix} {name}"


class FriendlyGreeter:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix}, {name}!"


@dataclass(slots=True)
class Tracer:
    events: list[str]

    def record(self, event: str) -> None:
        self.events.append(event)


class TracedGreeter:
    def __init__(self, inner: Greeter, tracer: Tracer) -> None:
        self.inner = inner
        self.tracer = tracer

    def greet(self, name: str) -> str:
        self.tracer.record("greet")
        return self.inner.greet(name)


class CountingGreeter:
    def __init__(self, inner: Greeter) -> None:
        self.inner = inner
        self.calls = 0

    def greet(self, name: str) -> str:
        self.calls += 1
        return self.inner.greet(name)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance("Hello", provides=str)
    tracer = Tracer(events=[])
    container.add_instance(tracer, provides=Tracer)
    container.add_concrete(SimpleGreeter, provides=Greeter)

    # Step 1: one decorator.
    container.decorate(provides=Greeter, decorator=TracedGreeter)
    traced_greeter = container.resolve(Greeter)
    traced_result = traced_greeter.greet("Sam")
    print(f"step1_outer={type(traced_greeter).__name__}")  # => step1_outer=TracedGreeter
    print(
        f"step1_inner={type(traced_greeter.inner).__name__}",
    )  # => step1_inner=SimpleGreeter
    print(
        f"step1_result={traced_result}",
    )  # => step1_result=Hello Sam
    print(f"step1_events={len(tracer.events)}")  # => step1_events=1

    # Step 2: add another decorator; this one becomes outermost.
    container.decorate(provides=Greeter, decorator=CountingGreeter)
    stacked_greeter = container.resolve(Greeter)
    stacked_result = stacked_greeter.greet("Pat")
    print(f"step2_outer={type(stacked_greeter).__name__}")  # => step2_outer=CountingGreeter
    print(f"step2_inner={type(stacked_greeter.inner).__name__}")  # => step2_inner=TracedGreeter
    print(
        f"step2_base={type(stacked_greeter.inner.inner).__name__}",
    )  # => step2_base=SimpleGreeter
    print(
        f"step2_result={stacked_result}",
    )  # => step2_result=Hello Pat
    print(f"step2_calls={stacked_greeter.calls}")  # => step2_calls=1

    # Step 3: replace the base binding; decorators remain.
    container.add_instance("Hi", provides=str)
    container.add_concrete(FriendlyGreeter, provides=Greeter)
    rebound_greeter = container.resolve(Greeter)
    rebound_result = rebound_greeter.greet("Lee")
    print(
        f"step3_base={type(rebound_greeter.inner.inner).__name__}",
    )  # => step3_base=FriendlyGreeter
    print(
        f"step3_result={rebound_result}",
    )  # => step3_result=Hi, Lee!


if __name__ == "__main__":
    main()
```

<a id="ex-21-decorators--02-decorate-before-registration-py"></a>
### 02_decorate_before_registration.py ([ex_21_decorators/02_decorate_before_registration.py](ex_21_decorators/02_decorate_before_registration.py))

Two readability-focused patterns.

1. ``decorate(...)`` can be called before ``add_*``.
2. ``inner_parameter=...`` removes ambiguity when inference is unclear.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from diwire import Component, Container
from diwire.exceptions import DIWireInvalidRegistrationError


class Repo:
    def get(self, key: str) -> str:
        raise NotImplementedError


class SqlRepo(Repo):
    def get(self, key: str) -> str:
        return f"sql:{key}"


PrimaryRepo = Annotated[Repo, Component("primary")]


@dataclass(slots=True)
class CachedRepo(Repo):
    inner: Repo
    cache_hits: int = 0

    def get(self, key: str) -> str:
        self.cache_hits += 1
        return self.inner.get(key)


class AmbiguousDecorator(Repo):
    def __init__(self, first: Repo, second: Repo) -> None:
        self.first = first
        self.second = second

    def get(self, key: str) -> str:
        return self.first.get(key)


def main() -> None:
    # Pattern A: decorate first, register later.
    container = Container(autoregister_concrete_types=False)
    container.decorate(
        provides=PrimaryRepo,
        decorator=CachedRepo,
        inner_parameter="inner",
    )
    container.add_concrete(SqlRepo, provides=PrimaryRepo)

    decorated = container.resolve(PrimaryRepo)
    print(f"pattern_a_outer={type(decorated).__name__}")
    print(f"pattern_a_inner={type(decorated.inner).__name__}")
    print(f"pattern_a_result={decorated.get('account-42')}")

    # Pattern B: ambiguous decorator needs explicit inner_parameter.
    ambiguous_error: str
    try:
        container.decorate(provides=Repo, decorator=AmbiguousDecorator)
    except DIWireInvalidRegistrationError as error:
        ambiguous_error = type(error).__name__
    print(ambiguous_error)

    container.decorate(
        provides=Repo,
        decorator=AmbiguousDecorator,
        inner_parameter="first",
    )
    container.add_concrete(SqlRepo, provides=Repo)
    resolved = container.resolve(Repo)
    print(f"pattern_b_error={ambiguous_error}")
    print(f"pattern_b_outer={type(resolved).__name__}")
    print(f"pattern_b_inner={type(resolved.first).__name__}")


if __name__ == "__main__":
    main()
```

<a id="ex-21-decorators--03-open-generic-decorate-py"></a>
### 03_open_generic_decorate.py ([ex_21_decorators/03_open_generic_decorate.py](ex_21_decorators/03_open_generic_decorate.py))

Open-generic decoration in one screen.

Register once for ``Repo[T]``, decorate once, then resolve many closed types.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from diwire import Container

T = TypeVar("T")


class Repo(Generic[T]):
    pass


@dataclass(slots=True)
class SqlRepo(Repo[T]):
    model: type[T]


@dataclass(slots=True)
class TimedRepo(Repo[T]):
    inner: Repo[T]


def build_repo(model: type[T]) -> Repo[T]:
    return SqlRepo(model=model)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_factory(build_repo, provides=Repo)
    container.decorate(provides=Repo, decorator=TimedRepo)

    int_repo = container.resolve(Repo[int])
    str_repo = container.resolve(Repo[str])

    print(f"outer_type={type(int_repo).__name__}")
    print(f"int_inner_type={type(int_repo.inner).__name__}")
    print(f"str_inner_type={type(str_repo.inner).__name__}")
    print(f"int_model_ok={int_repo.inner.model is int}")
    print(f"str_model_ok={str_repo.inner.model is str}")


if __name__ == "__main__":
    main()
```

<a id="ex-22-all-components"></a>
## 22. All Components

Files:
- [01_all_components.py](#ex-22-all-components--01-all-components-py)

<a id="ex-22-all-components--01-all-components-py"></a>
### 01_all_components.py ([ex_22_all_components/01_all_components.py](ex_22_all_components/01_all_components.py))

Resolve all implementations with ``All[T]`` (base + components).

This module demonstrates how to collect a plugin stack by combining:

- the plain registration for a base type ``T`` (if present), and
- all component registrations keyed as ``Annotated[T, Component(...)]``.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol, TypeAlias

from diwire import All, Component, Container, Injected, provider_context


class EventHandler(Protocol):
    def handle(self, event: str) -> str: ...


@dataclass(frozen=True, slots=True)
class BaseHandler:
    def handle(self, event: str) -> str:
        return f"base:{event}"


@dataclass(frozen=True, slots=True)
class LoggingHandler:
    def handle(self, event: str) -> str:
        return f"logging:{event}"


@dataclass(frozen=True, slots=True)
class MetricsHandler:
    def handle(self, event: str) -> str:
        return f"metrics:{event}"


Logging: TypeAlias = Annotated[EventHandler, Component("logging")]
Metrics: TypeAlias = Annotated[EventHandler, Component("metrics")]


def main() -> None:
    container = Container(autoregister_concrete_types=False)

    container.add_concrete(BaseHandler, provides=EventHandler)
    container.add_concrete(LoggingHandler, provides=Logging)
    container.add_concrete(MetricsHandler, provides=Metrics)

    handlers = container.resolve(All[EventHandler])
    print(
        [handler.handle("evt") for handler in handlers],
    )  # => ['base:evt', 'logging:evt', 'metrics:evt']

    @provider_context.inject
    def dispatch(event: str, handlers: Injected[All[EventHandler]]) -> tuple[str, ...]:
        return tuple(handler.handle(event) for handler in handlers)

    print(dispatch("evt"))  # => ('base:evt', 'logging:evt', 'metrics:evt')


if __name__ == "__main__":
    main()
```

<a id="ex-23-maybe"></a>
## 23. Maybe

Files:
- [01_maybe.py](#ex-23-maybe--01-maybe-py)

<a id="ex-23-maybe--01-maybe-py"></a>
### 01_maybe.py ([ex_23_maybe/01_maybe.py](ex_23_maybe/01_maybe.py))

Explicit optional dependencies with Maybe[T].

This topic demonstrates:

1. ``resolve(Maybe[T])`` returning ``None`` when ``T`` is not registered.
2. Constructor defaults being honored for missing ``Maybe[T]`` dependencies.
3. Missing ``Maybe[T]`` dependencies without defaults resolving as ``None``.
4. Registered values overriding defaults.
5. ``T | None`` (Optional) staying strict and raising when unregistered.

```python
from __future__ import annotations

from diwire import Container, Maybe
from diwire.exceptions import DIWireDependencyNotRegisteredError


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


_DEFAULT_CLIENT = object()


class ServiceWithDefault:
    def __init__(self, client: Maybe[ApiClient] = _DEFAULT_CLIENT) -> None:
        self.client = client


class ServiceWithoutDefault:
    def __init__(self, client: Maybe[ApiClient]) -> None:
        self.client = client


def strict_container() -> Container:
    return Container(
        autoregister_concrete_types=False,
        autoregister_dependencies=False,
    )


def main() -> None:
    container = strict_container()

    print(f"missing_maybe={container.resolve(Maybe[ApiClient])!r}")  # => missing_maybe=None

    container.add_concrete(ServiceWithDefault, provides=ServiceWithDefault)
    container.add_concrete(ServiceWithoutDefault, provides=ServiceWithoutDefault)

    with_default = container.resolve(ServiceWithDefault)
    without_default = container.resolve(ServiceWithoutDefault)
    print(
        f"default_honored={with_default.client is _DEFAULT_CLIENT}",
    )  # => default_honored=True
    print(f"missing_without_default={without_default.client!r}")  # => missing_without_default=None

    client = ApiClient(base_url="https://api.example.local")
    container.add_instance(client, provides=ApiClient)
    with_registered_client = container.resolve(ServiceWithDefault)
    print(
        f"registered_overrides_default={with_registered_client.client is client}",
    )  # => registered_overrides_default=True

    strict_optional = strict_container()
    try:
        strict_optional.resolve(ApiClient | None)
    except DIWireDependencyNotRegisteredError as error:
        print(
            f"optional_union_error={type(error).__name__}",
        )  # => optional_union_error=DIWireDependencyNotRegisteredError


if __name__ == "__main__":
    main()
```
<!-- END: AUTO-GENERATED EXAMPLES -->

Run one example:

```bash
uv run python examples/ex_XX_<topic>/01_<topic>.py
```

Validate expected output markers for all examples:

```bash
uv run pytest tests/examples/test_examples_expected_output.py
```

Or run the full suite:

```bash
make test
```
