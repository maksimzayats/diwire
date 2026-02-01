from __future__ import annotations

import contextlib
import io
import sys
import types
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.docs_examples import iter_rst_code_blocks


def _exec_block(*, code: str, filename: str) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    module = types.ModuleType("__main__")
    module.__dict__["__name__"] = "__main__"
    module.__dict__["__package__"] = None
    old_main = sys.modules.get("__main__")
    sys.modules["__main__"] = module

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(code, filename, "exec"), module.__dict__)  # noqa: S102
    finally:
        if old_main is None:
            del sys.modules["__main__"]
        else:
            sys.modules["__main__"] = old_main

    return module.__dict__


def test_docs_fastapi_examples_are_correct(capsys: Any) -> None:
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    blocks = iter_rst_code_blocks(docs_dir=docs_dir)

    fastapi_doc = docs_dir / "howto" / "examples" / "fastapi.rst"
    fastapi_blocks = sorted(
        [b for b in blocks if b.path == fastapi_doc and "diwire-example" in b.classes],
        key=lambda b: b.lineno,
    )
    assert len(fastapi_blocks) == 3, (
        "Expected 3 FastAPI examples in docs/howto/examples/fastapi.rst"
    )

    # Example 1: Basic integration.
    ns1 = _exec_block(
        code=fastapi_blocks[0].code,
        filename=f"{fastapi_blocks[0].path}:{fastapi_blocks[0].lineno}",
    )
    app1 = ns1["app"]
    client1 = TestClient(app1)
    response = client1.get("/greet")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "Hello from Service!" in data["message"]
    assert "request_id" in data
    captured = capsys.readouterr()
    assert "Closing service" in captured.out

    # Example 2: Decorator-based layering.
    ns2 = _exec_block(
        code=fastapi_blocks[1].code,
        filename=f"{fastapi_blocks[1].path}:{fastapi_blocks[1].lineno}",
    )
    app2 = ns2["app"]
    client2 = TestClient(app2)
    response = client2.get("/greet?name=TestUser")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "TestUser" in data["message"]
    assert "Hello" in data["message"]
    captured = capsys.readouterr()
    assert "Closing service" in captured.out

    # Example 3: container_context + middleware-managed request context.
    ns3 = _exec_block(
        code=fastapi_blocks[2].code,
        filename=f"{fastapi_blocks[2].path}:{fastapi_blocks[2].lineno}",
    )
    app3 = ns3["app"]
    setup_container = ns3["setup_container"]

    from diwire.container_context import _current_container

    setup_container()
    try:
        client3 = TestClient(app3)
        response = client3.get("/greet?name=Alice")
        assert response.status_code == 200
        assert "Alice" in response.json()["message"]

        response2 = client3.get("/greet?name=Bob")
        assert response2.status_code == 200
        assert "Bob" in response2.json()["message"]
        assert response2.json()["request_id"] != response.json()["request_id"]

        captured = capsys.readouterr()
        assert "Closing service" in captured.out
    finally:
        _current_container.set(None)
