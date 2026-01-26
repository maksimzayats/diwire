from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.params import Query

from diwire import Container, FromDI

app = FastAPI()
container = Container()


@app.get("/greet")
@container.resolve(scope="request")
async def handler(
    request: Request,
    name: Annotated[str, Query()],
    service: Annotated[Service, FromDI()],
) -> dict[str, str | int]:
    return {"message": service.greet(name), "request_id": id(request)}


@dataclass
class Service:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def greet(self, name: str) -> str:
        return f"Hello '{name}' from Service! With id: {self.id}"


async def get_service():
    try:
        yield Service()
    finally:
        print("Closing service")


container.register(Service, factory=get_service, scope="request")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
