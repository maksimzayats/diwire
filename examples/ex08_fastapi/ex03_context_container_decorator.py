from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.params import Query

from diwire import Container, FromDI, container_context

app = FastAPI()
request_context = ContextVar("request_context")


@app.middleware("http")
async def _(request: Request, call_next):
    token = request_context.set(request)
    try:
        return await call_next(request)
    finally:
        request_context.reset(token)


@app.get("/greet")
@container_context.resolve(scope="request")
async def handler(
    name: Annotated[str, Query()],
    service: Annotated[Service, FromDI()],
) -> dict[str, str | int]:
    request = request_context.get()
    return {"message": service.greet(name), "request_id": id(request)}


class Handler:
    @container_context.resolve(scope="request")
    async def handle(
        self,
        request: Request,
        name: Annotated[str, Query()],
        # service: Annotated[Service, FromDI()],
    ) -> dict[str, str | int]:
        service = await container_context.aresolve(Service)
        print(f"{service = }")
        return {"request_id": id(request)}


app.get("/greet/v2")(Handler().handle)


@dataclass
class Service:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def greet(self, name: str) -> str:
        return f"Hello '{name}' from Service! With id: {self.id}"


async def get_service(
    request: Request,
):
    print(f"{request = }")
    try:
        yield Service()
    finally:
        print("Closing service")


container = Container()
container_context.set_current(container)
print("Registering Service with request scope")

container.register(Request, factory=request_context.get, scope="request")
container.register(Service, factory=get_service, scope="request")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
