from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, Request

from diwire import Container, FromDI

app = FastAPI()
container = Container()


async def handler(request: Request, service: Annotated[Service, FromDI()]) -> dict:
    return {"message": service.greet(), "request_id": id(request)}


@dataclass
class Service:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def greet(self) -> str:
        return f"Hello from Service! With id: {self.id}"


async def get_service():
    try:
        yield Service()
    finally:
        print("Closing service")


container.register(Service, factory=get_service, scope="request")

app.add_api_route(
    "/greet",
    container.resolve(handler, scope="request"),
    methods=["GET"],
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
