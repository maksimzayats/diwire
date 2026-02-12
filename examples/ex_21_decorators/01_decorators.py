"""Decorators: tracing, stacking order, and base re-registration.

This example shows practical ``Container.decorate(...)`` usage:

1. Decorate an existing binding (``TracedHttpClient``).
2. Stack another decorator and confirm ordering (last call is outermost).
3. Re-register the base binding and keep the same decorator chain.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Protocol

from diwire import Container


class HttpClient(Protocol):
    def get(self, path: str) -> str: ...


class RequestsHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def get(self, path: str) -> str:
        return f"requests:{self.base_url}{path}"


class AltHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def get(self, path: str) -> str:
        return f"alt:{self.base_url}{path}"


@dataclass(slots=True)
class Tracer:
    spans: list[str] = field(default_factory=list)

    @contextmanager
    def span(self, name: str) -> Generator[None, None, None]:
        self.spans.append(name)
        yield


class TracedHttpClient:
    def __init__(self, inner: HttpClient, tracer: Tracer) -> None:
        self.inner = inner
        self.tracer = tracer

    def get(self, path: str) -> str:
        with self.tracer.span("http.get"):
            return self.inner.get(path)


class MetricsHttpClient:
    def __init__(self, inner: HttpClient) -> None:
        self.inner = inner
        self.calls = 0

    def get(self, path: str) -> str:
        self.calls += 1
        return self.inner.get(path)


def main() -> None:
    container = Container(autoregister_concrete_types=False)
    container.add_instance("https://api.example.com", provides=str)
    tracer = Tracer()
    container.add_instance(tracer, provides=Tracer)
    container.add_concrete(RequestsHttpClient, provides=HttpClient)

    container.decorate(provides=HttpClient, decorator=TracedHttpClient)
    traced_client = container.resolve(HttpClient)
    traced_result = traced_client.get("/health")
    print(f"traced_layer={type(traced_client).__name__}")  # => traced_layer=TracedHttpClient
    print(
        f"traced_inner={type(traced_client.inner).__name__}",
    )  # => traced_inner=RequestsHttpClient
    print(
        f"traced_result={traced_result}",
    )  # => traced_result=requests:https://api.example.com/health
    print(f"spans_after_traced={len(tracer.spans)}")  # => spans_after_traced=1

    container.decorate(provides=HttpClient, decorator=MetricsHttpClient)
    stacked_client = container.resolve(HttpClient)
    stacked_result = stacked_client.get("/users")
    print(f"stack_outer={type(stacked_client).__name__}")  # => stack_outer=MetricsHttpClient
    print(f"stack_inner={type(stacked_client.inner).__name__}")  # => stack_inner=TracedHttpClient
    print(
        f"stack_base={type(stacked_client.inner.inner).__name__}",
    )  # => stack_base=RequestsHttpClient
    print(
        f"stack_result={stacked_result}",
    )  # => stack_result=requests:https://api.example.com/users
    print(f"metric_calls={stacked_client.calls}")  # => metric_calls=1

    container.add_concrete(AltHttpClient, provides=HttpClient)
    rebound_client = container.resolve(HttpClient)
    rebound_result = rebound_client.get("/rebased")
    print(
        f"rebound_base={type(rebound_client.inner.inner).__name__}",
    )  # => rebound_base=AltHttpClient
    print(
        f"rebound_result={rebound_result}",
    )  # => rebound_result=alt:https://api.example.com/rebased


if __name__ == "__main__":
    main()
