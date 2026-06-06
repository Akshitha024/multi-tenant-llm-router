"""LRU adapter cache.

The real vLLM multi-LoRA server keeps adapters mapped into GPU memory and
swaps them in/out based on incoming request adapter ids. The cache here is
the routing-layer mirror of that: we track which adapters are "loaded" so
the chart layer can show hit/miss/swap behavior under load. The actual
weight loading happens on the vLLM side when we forward a request.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from loguru import logger

from ..types import AdapterId, CacheEvent


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    loads: int = 0
    evictions: int = 0

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0


class LRUAdapterCache:
    """Bookkeeping cache. .request(adapter_id) returns (was_cached, swap_ms)."""

    def __init__(self, capacity: int = 8, mock_swap_ms: float = 35.0) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.mock_swap_ms = mock_swap_ms
        self._order: OrderedDict[AdapterId, float] = OrderedDict()
        self.stats = CacheStats()
        self.events: list[CacheEvent] = []

    def request(self, adapter_id: AdapterId) -> tuple[bool, float]:
        if adapter_id in self._order:
            self._order.move_to_end(adapter_id)
            self.stats.hits += 1
            self.events.append(CacheEvent(adapter_id=adapter_id, kind="hit"))
            return True, 0.0

        self.stats.misses += 1
        self.stats.loads += 1
        if len(self._order) >= self.capacity:
            evicted, _ = self._order.popitem(last=False)
            self.stats.evictions += 1
            self.events.append(CacheEvent(adapter_id=evicted, kind="evict"))
        self._order[adapter_id] = time.time()
        self.events.append(
            CacheEvent(adapter_id=adapter_id, kind="miss", duration_ms=self.mock_swap_ms)
        )
        logger.debug(
            "cache miss for {}; loaded ({} of {} slots used)",
            adapter_id,
            len(self._order),
            self.capacity,
        )
        return False, self.mock_swap_ms

    def loaded(self) -> list[AdapterId]:
        return list(self._order.keys())
