"""Five charts for serving-router benchmarks.

Distinct from prior projects again:
  - throughput vs concurrency curve
  - latency CDF (one curve per adapter)
  - per-adapter request volume bar
  - cache-event timeline (load/hit/miss/evict over time)
  - cost-per-tenant stacked area
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def _read(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# 1. Throughput vs concurrency
def plot_throughput_vs_concurrency(log_path: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(log_path) if r.get("status") == 200]
    if not rows:
        out.write_bytes(b"")
        return out
    by_client: dict[int, list[float]] = {}
    for r in rows:
        by_client.setdefault(int(r["client"]), []).append(float(r["ts"]))
    # for each concurrency level k = 1..max, estimate tput as N/(elapsed)
    concs = sorted(by_client.keys())
    n_clients = len(concs) + 1  # client ids are 0-indexed
    tputs: list[float] = []
    levels = list(range(1, n_clients + 1))
    for k in levels:
        ts = []
        for cid in list(by_client.keys())[:k]:
            ts.extend(by_client[cid])
        if not ts:
            tputs.append(0.0)
            continue
        elapsed = max(ts) - min(ts)
        tputs.append(len(ts) / elapsed if elapsed > 0 else 0)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(levels, tputs, marker="o", linewidth=2)
    ax.set_xlabel("concurrent clients")
    ax.set_ylabel("requests / second (observed)")
    ax.set_title("Throughput vs concurrency")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# 2. Latency CDF per adapter
def plot_latency_cdf(log_path: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(log_path) if r.get("status") == 200 and "wall_ms" in r]
    if not rows:
        out.write_bytes(b"")
        return out
    by_adapter: dict[str, list[float]] = {}
    for r in rows:
        by_adapter.setdefault(str(r["adapter"]), []).append(float(r["wall_ms"]))
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for name, vals in sorted(by_adapter.items()):
        vs = np.sort(vals)
        cdf = np.arange(1, len(vs) + 1) / len(vs)
        ax.plot(vs, cdf, label=f"{name} (n={len(vs)})", linewidth=1.5)
    ax.set_xlabel("wall-clock latency (ms)")
    ax.set_ylabel("CDF")
    ax.set_title("Per-adapter latency CDF")
    ax.grid(True, alpha=0.3)
    if len(by_adapter) <= 12:
        ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# 3. Per-adapter request volume bar (sorted)
def plot_adapter_volume(log_path: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = _read(log_path)
    if not rows:
        out.write_bytes(b"")
        return out
    counts: dict[str, int] = {}
    for r in rows:
        a = str(r.get("adapter", ""))
        counts[a] = counts.get(a, 0) + 1
    items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    names = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(max(6, 0.35 * len(names) + 3), 4.5))
    ax.bar(names, vals, color="#1f77b4")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("requests")
    ax.set_title("Per-adapter request volume (sorted)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# 4. Cache hit/miss timeline
def plot_cache_timeline(log_path: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(log_path) if r.get("status") == 200 and "cache_hit" in r]
    if not rows:
        out.write_bytes(b"")
        return out
    rows.sort(key=lambda r: r["ts"])
    t0 = rows[0]["ts"]
    xs = [r["ts"] - t0 for r in rows]
    hits = [1 if r["cache_hit"] else 0 for r in rows]
    misses = [0 if r["cache_hit"] else 1 for r in rows]
    cum_hits = np.cumsum(hits)
    cum_misses = np.cumsum(misses)
    cum_total = cum_hits + cum_misses
    hit_rate = cum_hits / np.maximum(cum_total, 1)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(8, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax1.plot(xs, cum_hits, label="cumulative hits", color="#2ca02c", linewidth=1.5)
    ax1.plot(xs, cum_misses, label="cumulative misses", color="#d62728", linewidth=1.5)
    ax1.set_ylabel("cumulative requests")
    ax1.set_title("Cache events over time")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2.plot(xs, hit_rate, color="#1f77b4")
    ax2.set_xlabel("seconds since start")
    ax2.set_ylabel("rolling hit rate")
    ax2.set_ylim(0, 1)
    ax2.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# 5. Cost-per-adapter stacked bar
def plot_cost_per_adapter(log_path: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(log_path) if r.get("status") == 200 and "cost" in r]
    if not rows:
        out.write_bytes(b"")
        return out
    by_adapter: dict[str, float] = {}
    for r in rows:
        a = str(r.get("adapter", ""))
        by_adapter[a] = by_adapter.get(a, 0.0) + float(r["cost"])
    items = sorted(by_adapter.items(), key=lambda x: x[1], reverse=True)
    names = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(max(6, 0.35 * len(names) + 3), 4.5))
    ax.bar(names, vals, color="#9467bd")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("USD")
    total = sum(vals)
    ax.set_title(f"Per-adapter cost (total ${total:.4f})")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out
