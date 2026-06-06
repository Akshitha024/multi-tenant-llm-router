from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from router.routing.router_app import build_app

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    log = tmp_path / "log.jsonl"
    app = build_app(tenants_path=FIX / "tenants.yaml", cache_capacity=3, log_path=log)
    return TestClient(app)


def test_healthz_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauthenticated_rejected(client: TestClient) -> None:
    r = client.post(
        "/v1/generate",
        json={"tenant_id": "t1", "adapter_id": "a0", "prompt": "hi"},
    )
    assert r.status_code == 401


def test_tenant_mismatch_rejected(client: TestClient) -> None:
    # use t1's key but pretend to be t2
    r = client.post(
        "/v1/generate",
        json={"tenant_id": "t2", "adapter_id": "a0", "prompt": "hi"},
        headers={"Authorization": "Bearer secret-t1"},
    )
    assert r.status_code == 403


def test_adapter_not_allowed(client: TestClient) -> None:
    # t2 is only allowed a0 and a3
    r = client.post(
        "/v1/generate",
        json={"tenant_id": "t2", "adapter_id": "a5", "prompt": "hi"},
        headers={"Authorization": "Bearer secret-t2"},
    )
    assert r.status_code == 403


def test_happy_path(client: TestClient) -> None:
    r = client.post(
        "/v1/generate",
        json={"tenant_id": "t1", "adapter_id": "a0", "prompt": "hi there", "max_tokens": 4},
        headers={"Authorization": "Bearer secret-t1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "mock:a0" in body["text"]
    assert body["completion_tokens"] == 4
    assert body["latency_ms"] > 0
    assert body["cache_hit"] is False  # first call is a miss
    assert body["cost_usd"] > 0


def test_cache_hit_on_repeat(client: TestClient) -> None:
    headers = {"Authorization": "Bearer secret-t1"}
    payload = {"tenant_id": "t1", "adapter_id": "a0", "prompt": "x", "max_tokens": 4}
    r1 = client.post("/v1/generate", json=payload, headers=headers)
    r2 = client.post("/v1/generate", json=payload, headers=headers)
    assert r1.json()["cache_hit"] is False
    assert r2.json()["cache_hit"] is True
    # cache hit should be at least slightly faster (no swap cost)
    assert r2.json()["latency_ms"] <= r1.json()["latency_ms"] + 5
