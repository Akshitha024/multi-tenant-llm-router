"""FastAPI router app.

POST /v1/generate
  headers: Authorization: Bearer <api_key>
  body: {tenant_id, adapter_id, prompt, max_tokens, temperature}

Pipeline:
  1. authenticate (api key -> tenant)
  2. authorize  (adapter_id in tenant.allowed_adapters)
  3. rate limit (token-bucket per tenant)
  4. cache.request(adapter_id) -> hit/miss + swap latency
  5. backend.generate(req, adapter_ref)
  6. cost = (prompt + completion) * tenant.cost_per_1k_tokens_usd / 1000
  7. return response, log structured row to results/requests.jsonl
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from loguru import logger
from pydantic import BaseModel

from ..adapters.cache import LRUAdapterCache
from ..auth.keys import TenantStore
from ..types import AdapterRef, GenerateRequest
from .backend import Backend, MockBackend


class GenerateIn(BaseModel):
    tenant_id: str
    adapter_id: str
    prompt: str
    max_tokens: int = 64
    temperature: float = 0.0


class GenerateOut(BaseModel):
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cache_hit: bool
    cost_usd: float


def build_app(
    tenants_path: Path | None = None,
    cache_capacity: int = 8,
    backend: Backend | None = None,
    log_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="router", version="0.9.0")

    tenants = TenantStore()
    if tenants_path and tenants_path.exists():
        tenants.load(tenants_path)
    cache = LRUAdapterCache(capacity=cache_capacity)
    use_backend: Backend = backend or MockBackend()

    # in-memory token-bucket: tenant_id -> (tokens, last_refill_ts)
    bucket: dict[str, list[float]] = {}

    def _refill(tenant_id: str, rps: float) -> None:
        if tenant_id not in bucket:
            bucket[tenant_id] = [rps, time.time()]
            return
        tok, last = bucket[tenant_id]
        now = time.time()
        added = (now - last) * rps
        tok = min(rps, tok + added)
        bucket[tenant_id] = [tok, now]

    def _consume(tenant_id: str, rps: float) -> bool:
        _refill(tenant_id, rps)
        tok, last = bucket[tenant_id]
        if tok < 1:
            return False
        bucket[tenant_id] = [tok - 1, last]
        return True

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "cache_size": len(cache.loaded())}

    @app.post("/v1/generate", response_model=GenerateOut)
    async def generate(req: GenerateIn, authorization: str = Header(default="")) -> GenerateOut:
        api_key = authorization.removeprefix("Bearer ").strip()
        tenant = tenants.lookup(api_key)
        if tenant is None:
            raise HTTPException(status_code=401, detail="invalid api key")
        if tenant.tenant_id != req.tenant_id:
            raise HTTPException(status_code=403, detail="tenant_id mismatch")
        if req.adapter_id not in tenant.allowed_adapters:
            raise HTTPException(status_code=403, detail=f"adapter {req.adapter_id} not allowed")
        if not _consume(tenant.tenant_id, tenant.rate_limit_rps):
            raise HTTPException(status_code=429, detail="rate limit exceeded")

        was_cached, swap_ms = cache.request(req.adapter_id)
        adapter = AdapterRef(
            adapter_id=req.adapter_id,
            base_model="mock",
            path_or_hub_id=f"adapters/{req.adapter_id}",
            rank=8,
        )
        gen_req = GenerateRequest(
            tenant_id=req.tenant_id,
            adapter_id=req.adapter_id,
            prompt=req.prompt,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        backend_resp = await use_backend.generate(gen_req, adapter)
        backend_resp.cache_hit = was_cached
        backend_resp.latency_ms += swap_ms
        total_tokens = backend_resp.prompt_tokens + backend_resp.completion_tokens
        backend_resp.cost_usd = total_tokens * tenant.cost_per_1k_tokens_usd / 1000

        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "tenant_id": tenant.tenant_id,
                            "adapter_id": req.adapter_id,
                            "prompt_tokens": backend_resp.prompt_tokens,
                            "completion_tokens": backend_resp.completion_tokens,
                            "latency_ms": backend_resp.latency_ms,
                            "swap_ms": swap_ms,
                            "cache_hit": backend_resp.cache_hit,
                            "cost_usd": backend_resp.cost_usd,
                        }
                    )
                    + "\n"
                )
        logger.debug(
            "tenant={} adapter={} hit={} lat={:.1f}ms cost=${:.5f}",
            tenant.tenant_id,
            req.adapter_id,
            was_cached,
            backend_resp.latency_ms,
            backend_resp.cost_usd,
        )

        return GenerateOut(
            text=backend_resp.text,
            prompt_tokens=backend_resp.prompt_tokens,
            completion_tokens=backend_resp.completion_tokens,
            latency_ms=backend_resp.latency_ms,
            cache_hit=backend_resp.cache_hit,
            cost_usd=backend_resp.cost_usd,
        )

    return app
