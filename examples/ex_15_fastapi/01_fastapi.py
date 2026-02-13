"""FastAPI integration via ``@resolver_context.inject(scope=Scope.REQUEST)``.

This module demonstrates request-scoped injection without network startup:

1. A FastAPI route function decorated with ``@resolver_context.inject``.
2. A request-scoped generator resource that increments open/close counters.
3. Two in-process calls through ``TestClient``.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from diwire import Container, Injected, Lifetime, Scope, resolver_context


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
    @resolver_context.inject(scope=Scope.REQUEST)
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
