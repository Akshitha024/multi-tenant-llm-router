from __future__ import annotations

import pytest

from router.adapters.cache import LRUAdapterCache


def test_first_request_is_miss() -> None:
    c = LRUAdapterCache(capacity=3)
    hit, swap = c.request("a")
    assert hit is False
    assert swap > 0
    assert c.stats.misses == 1
    assert c.stats.hits == 0


def test_repeat_is_hit() -> None:
    c = LRUAdapterCache(capacity=3)
    c.request("a")
    hit, swap = c.request("a")
    assert hit is True
    assert swap == 0.0
    assert c.stats.hits == 1


def test_eviction_lru() -> None:
    c = LRUAdapterCache(capacity=2)
    c.request("a")
    c.request("b")
    c.request("a")  # touch a
    c.request("c")  # should evict b (b is LRU)
    assert "b" not in c.loaded()
    assert "a" in c.loaded()
    assert "c" in c.loaded()


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        LRUAdapterCache(capacity=0)


def test_hit_rate() -> None:
    c = LRUAdapterCache(capacity=4)
    for _ in range(3):
        c.request("a")
    for _ in range(7):
        c.request("b")
    # a: 1 miss + 2 hits; b: 1 miss + 6 hits
    # total: 2 misses + 8 hits = 0.8 hit rate
    assert c.stats.hit_rate() == 0.8
