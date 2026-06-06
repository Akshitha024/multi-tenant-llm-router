"""Core types: AdapterRef, GenerateRequest/Response, Tenant config."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

AdapterId = str
TenantId = str


@dataclass(frozen=True)
class AdapterRef:
    adapter_id: AdapterId
    base_model: str
    path_or_hub_id: str
    rank: int


@dataclass(frozen=True)
class Tenant:
    tenant_id: TenantId
    api_key: str
    allowed_adapters: tuple[AdapterId, ...]
    rate_limit_rps: float = 10.0
    cost_per_1k_tokens_usd: float = 0.001


@dataclass(frozen=True)
class GenerateRequest:
    tenant_id: TenantId
    adapter_id: AdapterId
    prompt: str
    max_tokens: int = 64
    temperature: float = 0.0


@dataclass
class GenerateResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cache_hit: bool
    cost_usd: float


@dataclass
class CacheEvent:
    ts: float = field(default_factory=time.time)
    adapter_id: AdapterId = ""
    kind: Literal["hit", "miss", "load", "evict"] = "hit"
    duration_ms: float = 0.0
