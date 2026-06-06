"""vLLM backend protocol + mock impl.

The real backend is a vLLM OpenAI-compatible server with `--enable-lora`
running on a GPU. The mock backend simulates token-by-token generation so
the router has something to talk to in CI and for local development.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Protocol

from ..types import AdapterRef, GenerateRequest, GenerateResponse


class Backend(Protocol):
    async def generate(self, req: GenerateRequest, adapter: AdapterRef) -> GenerateResponse: ...


@dataclass
class MockBackend:
    """Pretends to generate. Latency = base + per-token * max_tokens + jitter."""

    base_latency_ms: float = 12.0
    per_token_ms: float = 4.0
    jitter_ms: float = 4.0
    seed: int = 7

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    async def generate(self, req: GenerateRequest, adapter: AdapterRef) -> GenerateResponse:
        # token count: ~ 1 token per 4 chars on the prompt + max_tokens
        prompt_tokens = max(1, len(req.prompt) // 4)
        completion_tokens = req.max_tokens
        sim_ms = (
            self.base_latency_ms
            + self.per_token_ms * completion_tokens
            + self._rng.uniform(0, self.jitter_ms)
        )
        # actually sleep for a small fraction so timing-based tests are real
        t0 = time.perf_counter()
        await asyncio.sleep(sim_ms / 1000.0 / 10.0)
        observed_ms = (time.perf_counter() - t0) * 1000.0
        return GenerateResponse(
            text=f"[mock:{adapter.adapter_id}] " + req.prompt[:40] + " ...",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=max(observed_ms, sim_ms),
            cache_hit=False,
            cost_usd=0.0,
        )
