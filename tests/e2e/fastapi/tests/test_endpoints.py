from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest

_BASE_HTTP_URL_ENV = "FASTAPI_E2E_BASE_HTTP_URL"
_BASE_WS_URL_ENV = "FASTAPI_E2E_BASE_WS_URL"

if os.getenv(_BASE_HTTP_URL_ENV) is None:
    pytest.skip(
        f"{_BASE_HTTP_URL_ENV} is not set; skipping docker-compose FastAPI e2e tests.",
        allow_module_level=True,
    )

try:
    from websockets.asyncio.client import connect
except ModuleNotFoundError:
    pytest.skip(
        "websockets is not installed; skipping docker-compose FastAPI e2e tests.",
        allow_module_level=True,
    )


def _base_http_url() -> str:
    return os.getenv(_BASE_HTTP_URL_ENV, "http://api:8220").rstrip("/")


def _base_ws_url() -> str:
    return os.getenv(_BASE_WS_URL_ENV, "ws://api:8220").rstrip("/")


@pytest.fixture()
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=_base_http_url(), timeout=10.0) as client:
        yield client


@pytest.mark.asyncio
async def test_health_returns_ok(http_client: httpx.AsyncClient) -> None:
    response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.json() == "OK"


@pytest.mark.asyncio
async def test_request_based_returns_request_path(http_client: httpx.AsyncClient) -> None:
    response = await http_client.get("/services/request-based")
    assert response.status_code == 200
    assert response.json() == "Request path: /services/request-based"


@pytest.mark.asyncio
async def test_request_based_with_custom_state_returns_custom_state_value(
    http_client: httpx.AsyncClient,
) -> None:
    response = await http_client.get("/services/request-based-with-custom-state")
    assert response.status_code == 200
    assert response.json() == "Custom state value: /services/request-based-with-custom-state"


@pytest.mark.asyncio
async def test_context_manager_service_returns_cmservice_working(
    http_client: httpx.AsyncClient,
) -> None:
    response = await http_client.get("/services/cm-service")
    assert response.status_code == 200
    assert response.json() == "CMService working"


@pytest.mark.asyncio
async def test_websocket_request_based_with_custom_state_returns_ws_path() -> None:
    path = "/services/request-based-with-custom-state"
    async with connect(f"{_base_ws_url()}{path}", open_timeout=10.0) as websocket:
        await websocket.send("ping")
        payload = await websocket.recv()
    assert payload == f"WebSocket path: {path}"


@pytest.mark.asyncio
async def test_async_leaf_factory_returns_fresh_values(http_client: httpx.AsyncClient) -> None:
    tokens: list[str] = []
    for _ in range(2):
        response = await http_client.get("/services/async-leaf")
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"kind", "token"}
        assert payload["kind"] == "async-leaf"
        tokens.append(str(UUID(payload["token"])))
    assert len(set(tokens)) == 2


@pytest.mark.asyncio
async def test_async_leaf_factory_handles_parallel_requests(
    http_client: httpx.AsyncClient,
) -> None:
    responses = await asyncio.gather(
        *(http_client.get("/services/async-leaf") for _ in range(24)),
    )
    tokens: list[str] = []
    for response in responses:
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"kind", "token"}
        assert payload["kind"] == "async-leaf"
        tokens.append(str(UUID(payload["token"])))
    assert len(set(tokens)) == 24


@pytest.mark.asyncio
async def test_cached_async_factory_is_scoped_and_resource_cleanup_finishes(
    http_client: httpx.AsyncClient,
) -> None:
    before_response = await http_client.get("/services/cached-async-counts")
    assert before_response.status_code == 200
    before = before_response.json()
    tokens: list[str] = []
    resources: list[str] = []
    for _ in range(2):
        response = await http_client.get("/services/cached-async-leaf")
        assert response.status_code == 200
        payload = response.json()
        assert payload["same"] is True
        tokens.append(str(UUID(payload["token"])))
        resources.append(str(UUID(payload["resource"])))
    assert len(set(tokens)) == len(set(resources)) == 2
    after_response = await http_client.get("/services/cached-async-counts")
    assert after_response.status_code == 200
    after = after_response.json()
    assert {key: after[key] - before[key] for key in before} == {
        "created": 2,
        "opened": 2,
        "closed": 2,
    }


@pytest.mark.asyncio
async def test_cached_async_factory_isolated_for_parallel_requests(
    http_client: httpx.AsyncClient,
) -> None:
    before_response = await http_client.get("/services/cached-async-counts")
    assert before_response.status_code == 200
    before = before_response.json()
    responses = await asyncio.gather(
        *(http_client.get("/services/cached-async-leaf") for _ in range(24)),
    )
    tokens: list[str] = []
    resources: list[str] = []
    for response in responses:
        assert response.status_code == 200
        payload = response.json()
        assert payload["same"] is True
        tokens.append(str(UUID(payload["token"])))
        resources.append(str(UUID(payload["resource"])))
    assert len(set(tokens)) == len(set(resources)) == 24
    after_response = await http_client.get("/services/cached-async-counts")
    assert after_response.status_code == 200
    after = after_response.json()
    assert {key: after[key] - before[key] for key in before} == {
        "created": 24,
        "opened": 24,
        "closed": 24,
    }


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.asyncio
async def test_none_instance_resolves_in_serial_and_parallel_requests(
    http_client: httpx.AsyncClient,
    *,
    parallel: bool,
) -> None:
    path = "/services/none-instance"
    if parallel:
        responses = await asyncio.gather(*(http_client.get(path) for _ in range(24)))
    else:
        responses = [await http_client.get(path) for _ in range(2)]
    for response in responses:
        assert response.status_code == 200
        assert response.json() == {
            "injected": True,
            "sync": True,
            "async": True,
            "collection": True,
        }
