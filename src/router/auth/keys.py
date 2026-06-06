"""Tenant key store + lookup.

Loads a YAML file of {tenant_id: {api_key, allowed_adapters, rate_limit_rps,
cost_per_1k_tokens_usd}}. Constant-time comparison on the API key check.
"""

from __future__ import annotations

import hmac
from pathlib import Path

import yaml
from loguru import logger

from ..types import Tenant


class TenantStore:
    def __init__(self) -> None:
        self._by_id: dict[str, Tenant] = {}
        self._by_key: dict[str, Tenant] = {}

    def load(self, path: Path) -> None:
        raw = yaml.safe_load(path.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"tenants file at {path} must be a mapping")
        for tid, cfg in raw.items():
            t = Tenant(
                tenant_id=str(tid),
                api_key=str(cfg["api_key"]),
                allowed_adapters=tuple(str(a) for a in cfg.get("allowed_adapters", [])),
                rate_limit_rps=float(cfg.get("rate_limit_rps", 10.0)),
                cost_per_1k_tokens_usd=float(cfg.get("cost_per_1k_tokens_usd", 0.001)),
            )
            self._by_id[t.tenant_id] = t
            self._by_key[t.api_key] = t
        logger.info("loaded {} tenants from {}", len(self._by_id), path)

    def lookup(self, api_key: str) -> Tenant | None:
        # constant-time comparison to avoid timing oracles on prefix matches
        for key, tenant in self._by_key.items():
            if hmac.compare_digest(key, api_key):
                return tenant
        return None

    def get(self, tid: str) -> Tenant | None:
        return self._by_id.get(tid)

    def all(self) -> list[Tenant]:
        return list(self._by_id.values())
