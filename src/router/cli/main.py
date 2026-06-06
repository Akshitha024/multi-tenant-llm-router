from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..bench.load import LoadConfig
from ..bench.load import run as run_load
from ..routing.router_app import build_app
from ..viz.charts import (
    plot_adapter_volume,
    plot_cache_timeline,
    plot_cost_per_adapter,
    plot_latency_cdf,
    plot_throughput_vs_concurrency,
)

app = typer.Typer(add_completion=False, help="router: multi-LoRA serving router")


@app.command("serve")
def cmd_serve(
    port: Annotated[int, typer.Option(help="port")] = 8765,
    tenants: Annotated[Path, typer.Option(help="tenants yaml path")] = Path(
        "tests/fixtures/tenants.yaml"
    ),
    capacity: Annotated[int, typer.Option(help="adapter cache capacity")] = 8,
    log_path: Annotated[Path, typer.Option(help="per-request log jsonl")] = Path(
        "results/requests.jsonl"
    ),
) -> None:
    import uvicorn

    application = build_app(tenants_path=tenants, cache_capacity=capacity, log_path=log_path)
    uvicorn.run(application, host="0.0.0.0", port=port, log_level="info")


@app.command("bench")
def cmd_bench(
    base_url: Annotated[
        str, typer.Option(help="base url of running router")
    ] = "http://localhost:8765",
    tenant_id: Annotated[str, typer.Option(help="tenant id to load-test")] = "t1",
    api_key: Annotated[str, typer.Option(help="api key for the tenant")] = "secret-t1",
    adapters: Annotated[int, typer.Option(help="adapter count to cycle through")] = 10,
    rps: Annotated[float, typer.Option(help="per-client request rate")] = 5.0,
    duration: Annotated[float, typer.Option(help="seconds")] = 20.0,
    concurrency: Annotated[int, typer.Option(help="concurrent clients")] = 8,
    out: Annotated[Path, typer.Option(help="output jsonl")] = Path("results/load_log.jsonl"),
) -> None:
    adapter_ids = tuple(f"a{i}" for i in range(adapters))
    cfg = LoadConfig(
        base_url=base_url,
        api_key=api_key,
        tenant_id=tenant_id,
        adapter_ids=adapter_ids,
        rps=rps,
        duration_s=duration,
        concurrency=concurrency,
        out_path=out,
    )
    p = run_load(cfg)
    typer.echo(f"wrote {p}")


@app.command("plots")
def cmd_plots(
    log_path: Annotated[Path, typer.Option(help="load log jsonl")] = Path("results/load_log.jsonl"),
    out_dir: Annotated[Path, typer.Option(help="figures dir")] = Path("results/figures"),
) -> None:
    plot_throughput_vs_concurrency(log_path, out_dir / "throughput_vs_concurrency.png")
    plot_latency_cdf(log_path, out_dir / "latency_cdf.png")
    plot_adapter_volume(log_path, out_dir / "adapter_volume.png")
    plot_cache_timeline(log_path, out_dir / "cache_timeline.png")
    plot_cost_per_adapter(log_path, out_dir / "cost_per_adapter.png")
    typer.echo(f"wrote 5 figures to {out_dir}")


if __name__ == "__main__":
    app()
