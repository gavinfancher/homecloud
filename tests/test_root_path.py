from fastapi import FastAPI
from fastapi.testclient import TestClient

from homecloud.api.routes import public_router


def _client(root_path: str) -> TestClient:
    app = FastAPI(root_path=root_path)
    app.include_router(public_router)
    return TestClient(app)


def test_api_answers_with_and_without_the_tunnel_prefix():
    client = _client("/homecloud")
    # Through the tunnel (prefix kept) and from the host's health check.
    assert client.get("/homecloud/api/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}


def test_docs_point_at_the_prefixed_openapi():
    client = _client("/homecloud")
    assert "/homecloud/openapi.json" in client.get("/homecloud/docs").text
