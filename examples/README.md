# diwire Examples

This directory contains examples demonstrating diwire's features, organized by topic.

## Running Examples

```bash
# Run any example directly
uv run python examples/ex01_basics/ex01_registration.py

# For FastAPI examples, the server starts on http://localhost:8000
uv run python examples/ex08_fastapi/ex01_basic.py
```

## Directory Structure

### ex01_basics/ - Core Concepts

| File                                                                       | Description                                              |
|----------------------------------------------------------------------------|----------------------------------------------------------|
| [ex01_registration.py](ex01_basics/ex01_registration.py)                   | Three registration methods: class, factory, and instance |
| [ex02_lifetimes.py](ex01_basics/ex02_lifetimes.py)                         | TRANSIENT vs SINGLETON lifetimes                         |
| [ex03_constructor_injection.py](ex01_basics/ex03_constructor_injection.py) | Automatic dependency resolution via type hints           |
| [ex05_open_generics.py](ex01_basics/ex05_open_generics.py)                 | Open generic factory registration                        |

### ex02_scopes/ - Scoped Dependencies

| File                                                                   | Description                                           |
|------------------------------------------------------------------------|-------------------------------------------------------|
| [ex01_scope_basics.py](ex02_scopes/ex01_scope_basics.py)               | Using `enter_scope()` context manager                 |
| [ex02_scoped_singleton.py](ex02_scopes/ex02_scoped_singleton.py)       | SCOPED lifetime for request-local instances |
| [ex03_nested_scopes.py](ex02_scopes/ex03_nested_scopes.py)             | Nested scope hierarchies                              |
| [ex04_generator_factories.py](ex02_scopes/ex04_generator_factories.py) | Generator factories with cleanup on scope exit        |

### ex03_function_injection/ - Function-Level DI

| File                                                                         | Description                                             |
|------------------------------------------------------------------------------|---------------------------------------------------------|
| [ex01_injected.py](ex03_function_injection/ex01_injected.py)                 | `Annotated[T, Injected()]` marker for function parameters |
| [ex02_injected_wrapper.py](ex03_function_injection/ex02_injected_wrapper.py) | `InjectedFunction` wrapper for standalone functions             |
| [ex03_scoped_injected.py](ex03_function_injection/ex03_scoped_injected.py)   | `ScopedInjectedFunction` for scoped function injection          |

### ex04_components/ - Named Components

| File                                                                 | Description                                       |
|----------------------------------------------------------------------|---------------------------------------------------|
| [ex01_named_components.py](ex04_components/ex01_named_components.py) | Multiple implementations with `Component` markers |

### ex05_patterns/ - Real-World Patterns

| File                                                                           | Description                                         |
|--------------------------------------------------------------------------------|-----------------------------------------------------|
| [ex01_request_handler.py](ex05_patterns/ex01_request_handler.py)               | HTTP request handling with per-request scopes       |
| [ex02_repository.py](ex05_patterns/ex02_repository.py)                         | Repository pattern with scoped database sessions    |
| [ex03_class_methods.py](ex05_patterns/ex03_class_methods.py)                   | `container_context.resolve()` on instance methods   |
| [ex04_interface_registration.py](ex05_patterns/ex04_interface_registration.py) | Programming to interfaces with `provides` parameter |

### ex06_async/ - Async Support

| File                                                                            | Description                                      |
|---------------------------------------------------------------------------------|--------------------------------------------------|
| [ex01_basic_async_factory.py](ex06_async/ex01_basic_async_factory.py)           | Async factories with `aresolve()`                |
| [ex02_async_generator_cleanup.py](ex06_async/ex02_async_generator_cleanup.py)   | Async generators for resource cleanup            |
| [ex03_async_injected_functions.py](ex06_async/ex03_async_injected_functions.py) | `AsyncInjectedFunction` wrapper                          |
| [ex04_async_scoped_injection.py](ex06_async/ex04_async_scoped_injection.py)     | `AsyncScopedInjectedFunction` for scoped async functions |
| [ex05_mixed_and_parallel.py](ex06_async/ex05_mixed_and_parallel.py)             | Mixing sync/async and parallel resolution        |
| [ex06_error_handling.py](ex06_async/ex06_error_handling.py)                     | Error handling in async contexts                 |
| [ex07_fastapi_style.py](ex06_async/ex07_fastapi_style.py)                       | FastAPI-style async patterns                     |

### ex07_errors/ - Error Handling

| File                                                                   | Description                                           |
|------------------------------------------------------------------------|-------------------------------------------------------|
| [ex01_circular_dependency.py](ex07_errors/ex01_circular_dependency.py) | Circular dependency detection                         |
| [ex02_missing_dependency.py](ex07_errors/ex02_missing_dependency.py)   | Missing dependency errors                             |
| [ex03_scope_mismatch.py](ex07_errors/ex03_scope_mismatch.py)           | Scope mismatch errors (singleton depending on scoped) |

### ex08_fastapi/ - FastAPI Integration

| File                                                                                    | Description                                              |
|-----------------------------------------------------------------------------------------|----------------------------------------------------------|
| [ex01_basic.py](ex08_fastapi/ex01_basic.py)                                             | Manual route registration with `container.resolve()`     |
| [ex02_decorator.py](ex08_fastapi/ex02_decorator.py)                                     | Decorator pattern with layered dependencies              |
| [ex03_context_container_decorator.py](ex08_fastapi/ex03_context_container_decorator.py) | Global container with `container_context` and middleware |

## Recommended Learning Path

1. **Start here**: `ex01_basics/` - Understand registration, lifetimes, and constructor injection
2. **Scopes**: `ex02_scopes/` - Learn request-scoped dependencies
3. **Functions**: `ex03_function_injection/` - Inject into functions, not just classes
4. **Patterns**: `ex05_patterns/` - See real-world usage patterns
5. **Async**: `ex06_async/` - Async factories and resolution
6. **FastAPI**: `ex08_fastapi/` - Web framework integration
