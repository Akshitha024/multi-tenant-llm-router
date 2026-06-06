"""Synthetic load generator.

Spawns N concurrent clients, each sending requests at a Poisson rate of
RPS. Each request picks an adapter at random from the tenant's allowed
set, optionally biased toward a small "hot" subset to test cache locality.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


@dataclass
class LoadConfig:
    base_url: str = "http://localhost:8765"
    api_key: str = ""
    tenant_id: str = "t1"
    adapter_ids: tuple[str, ...] = ()
    hot_share: float = 0.7  # 70% of requests target the first ~3 adapters
    rps: float = 5.0
    duration_s: float = 30.0
    concurrency: int = 8
    out_path: Path = Path("results/load_log.jsonl")
    seed: int = 11


async def _one_client(cfg: LoadConfig, client_id: int, out_lines: list[dict[str, Any]]) -> None:
    rng = random.Random(cfg.seed + client_id)
    hot = list(cfg.adapter_ids[:3])
    rest = list(cfg.adapter_ids[3:])
    inter_arrival = 1.0 / max(cfg.rps, 0.01)
    end_time = time.time() + cfg.duration_s
    async with httpx.AsyncClient(base_url=cfg.base_url, timeout=30.0) as http:
        while time.time() < end_time:
            adapter = (
                rng.choice(hot) if hot and rng.random() < cfg.hot_share else rng.choice(rest or hot)
            )
            t0 = time.time()
            try:
                r = await http.post(
                    "/v1/generate",
                    json={
                        "tenant_id": cfg.tenant_id,
                        "adapter_id": adapter,
                        "prompt": f"Client {client_id} req at {t0:.3f}",
                        "max_tokens": 32,
                    },
                    headers={"Authorization": f"Bearer {cfg.api_key}"},
                )
                lat = (time.time() - t0) * 1000
                if r.status_code != 200:
                    out_lines.append(
                        {
                            "ts": t0,
                            "adapter": adapter,
                            "status": r.status_code,
                            "wall_ms": lat,
                            "client": client_id,
                        }
                    )
                else:
                    payload = r.json()
                    out_lines.append(
                        {
                            "ts": t0,
                            "adapter": adapter,
                            "status": 200,
                            "wall_ms": lat,
                            "client": client_id,
                            "server_ms": payload["latency_ms"],
                            "cache_hit": payload["cache_hit"],
                            "cost": payload["cost_usd"],
                        }
                    )
            except httpx.HTTPError as e:
                out_lines.append(
                    {
                        "ts": t0,
                        "adapter": adapter,
                        "status": -1,
                        "error": str(e),
                        "client": client_id,
                    }
                )
            jitter = rng.expovariate(1.0 / inter_arrival)
            await asyncio.sleep(jitter)


async def run_async(cfg: LoadConfig) -> Path:
    out_lines: list[dict[str, Any]] = []
    workers = [_one_client(cfg, i, out_lines) for i in range(cfg.concurrency)]
    await asyncio.gather(*workers)
    cfg.out_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg.out_path.open("w") as f:
        for row in out_lines:
            f.write(json.dumps(row) + "\n")
    logger.info("load test wrote {} requests to {}", len(out_lines), cfg.out_path)
    return cfg.out_path


def run(cfg: LoadConfig) -> Path:
    return asyncio.run(run_async(cfg))
