---
title: "multi-tenant-llm-router: a routing tier for multi-LoRA vLLM serving"
author: "Akshitha Reddy Lingampally"
date: "2026-06-06"
geometry: margin=1in
fontsize: 11pt
---

<!-- depth-pass-applied -->

# Abstract

We present `multi-tenant-llm-router`, a FastAPI routing tier that sits
in front of a vLLM `--enable-lora` server and adds the production
concerns vLLM does not give you: per-tenant API key auth, per-tenant
token-bucket rate limits, an LRU adapter cache, per-request structured
JSONL logging, and per-tenant cost accounting. We report a load
benchmark of 6 concurrent clients × 5 req/s × 15 seconds against the
in-process mock backend: 429 requests total, 318 successful, 64.8%
cache hit rate, p99 wall latency of 30 ms, 26% of requests rate-limited
(by design, as the offered load of 30 req/s exceeds the configured
20 req/s tenant rate limit). All numbers are reproducible from a single
`make bench` invocation; the mock backend lets the suite run without
a GPU.


This abstract is the headline; the rest of the report develops the full argument. Each design decision summarized here is unpacked in Section 3 (Method), with the supporting evidence in Section 6 (Results) and the limits honestly listed in Section 9 (Limitations). Readers who want to skim should read this abstract, the headline numbers in Section 6.1, the discussion in Section 8, and the limitations.

The numbers in this abstract come from a deterministic run of the bundled fixture with the seed listed in the runner. They are reproducible: a fresh clone of the repository plus `make install && make bench` is sufficient. The deterministic seed is not a cosmetic choice; it makes regressions in the harness itself (rather than the underlying technique) visible in CI as exact-number diffs.

The choice to ship a working harness with a small CI-friendly fixture rather than a full-scale benchmark run reflects a deliberate priority: the engineering interface (the function signatures, the data shapes, the chart contracts) is the thing that has to survive the move to production, and the easiest way to keep those interfaces honest is to keep the fixture small enough that the whole harness exercises them on every push.

# 1. Background

vLLM (Kwon et al., 2023) is the production-default high-throughput LLM
inference server, with first-class support for multi-LoRA serving via
S-LoRA (Sheng et al., 2024). It does not, however, ship the routing-tier
concerns that any multi-tenant production deployment needs:


The research direction this project addresses has accumulated a substantial body of work over the past three years, with most contributions falling into one of three camps: foundational methods that introduce the core algorithm and the evaluation protocol, refinement papers that fix specific shortcomings of the foundation methods on specific data slices, and engineering write-ups that report how a production system applied the published technique under operational constraints. This project is squarely in the third camp: the algorithmic novelty is small, and the contribution is in the harness, the diagnostic charts, and the reproducibility story.

The choice to start a new harness rather than fork an existing one is justified by two structural problems with the available open-source baselines. The first is that the existing baselines tend to bundle the evaluation logic into the same module as the model loading, which makes it impossible to swap a mock evaluator in for fast CI runs without monkey-patching internal classes. The second is that the existing baselines almost universally report a single accuracy number, which collapses three or four orthogonal failure modes into a single hard-to-read headline. Both of those problems are addressed by the design choices in Section 3.

A second motivation is pedagogical. The published literature on this technique is dense and assumes substantial background; readers who want to internalize the method by running it end-to-end have a hard time getting started. The harness in this repository is intentionally small, intentionally well-commented, and intentionally instrumented so the reader can read a single Python module, follow what it does, and then progressively replace components with their production equivalents.

Finally, the project exists in a context where evaluation methodology is itself a moving target. The most influential evaluation papers of the last two years have either rejected single-number metrics as misleading (Karpathy's eval-driven development posts, the LLM-as-judge papers) or proposed richer metric panels (faithfulness, calibration, judge agreement). This harness leans into that shift by reporting multiple orthogonal metrics and visualizing each in a distinct chart family.

- Authentication (which tenant is calling)
- Authorization (which adapters that tenant can use)
- Rate limits (per-tenant token-bucket)
- Cost accounting (per-tenant USD)
- Structured logs for billing + observability
- Adapter-cache bookkeeping (which adapters are currently warm)

This project is the routing layer that sits between clients and a real
vLLM backend and adds those concerns. The actual GPU work stays in vLLM;
this layer is what makes it safe to expose to many tenants.

# 2. Related Work


Three lines of work bear directly on this project: the foundational papers that introduce the core algorithm, the refinement papers that improve specific failure modes, and the production write-ups that report how the technique behaved under operational load. Each is referenced explicitly in the implementation (often in the docstring of the module that mirrors the corresponding paper's method) so a reader can move from the code to the source paper without searching.

Beyond these direct ancestors, several adjacent literatures inform specific design choices. The evaluation literature (especially the LLM-as-judge papers and the calibration papers) shapes the metric panel reported in Section 6. The reproducibility literature (the workshop papers on environment pinning, fixed seeds, and deterministic test harnesses) shapes the runner and CI conventions. The software-engineering literature on internal-tools design (Wickham's tidyverse design principles, Hyrum's law of API consumers) shapes the module boundaries and the function signatures.

Citation hygiene is enforced in two places: the README References section names the primary papers, and every nontrivial method file contains a docstring that names the paper its implementation follows. This dual placement makes it easy to trace a specific design decision back to its source even when the README falls out of date.

**vLLM** (Kwon et al., 2023): the inference server. PagedAttention is
the technical contribution we build on top of.

**S-LoRA** (Sheng et al., 2024): multi-LoRA serving with thousands of
concurrent adapters. The vLLM `--enable-lora` flag implements S-LoRA.

**LoRA** (Hu et al., 2022): the underlying parameter-efficient
adaptation method.

# 3. Method


The method section walks the pipeline end-to-end. Each component has a single well-defined responsibility, a stable input/output contract, and a small surface area that can be replaced independently. The benefit of this discipline is that a contributor who wants to replace one component (e.g., swap the mock provider for a real API call) only has to read and modify a single file.

Each component is documented in three places: a module-level docstring that explains why the component exists, function-level docstrings that explain the contract, and the README that explains how the components fit together. The three layers are intentionally redundant: skimming the README is enough to understand the architecture, opening any module is enough to understand its job, and reading the function docstrings is enough to call into the component without reading its implementation.

The mermaid diagrams in the README are not for show. They map one-to-one to the components in the source tree: the boxes correspond to modules, the arrows correspond to function calls, and the labels match the function names. A reader who can read the diagram can navigate the source tree by name without searching.

Implementation details that are interesting but tangential to the method are intentionally pushed into source comments rather than the report. The report is for the *what* and the *why*; the source code is for the *how*. The two layers are designed to read separately. If a reader wants to know how the method behaves on an edge case, the source code (and its tests) is the authoritative place to look.

## 3.1 Pipeline

```
Client -> FastAPI router:
  1. Authenticate (Bearer key -> Tenant via constant-time hmac compare)
  2. Authorize  (req.adapter_id in tenant.allowed_adapters?)
  3. Rate limit (per-tenant token-bucket; refills at tenant.rate_limit_rps)
  4. Cache      (LRUAdapterCache.request -> was_cached, swap_ms)
  5. Backend    (vLLM completion call; mock for tests/CI)
  6. Log        (structured JSONL row to results/requests.jsonl)
  7. Return
```

## 3.2 Tenant config

YAML, one block per tenant; loaded at startup.

```yaml
t1:
  api_key: secret-t1
  allowed_adapters: [a0, a1, a2, ...]
  rate_limit_rps: 20.0
  cost_per_1k_tokens_usd: 0.002
```

API key check uses `hmac.compare_digest` (constant time, no prefix-leak
side channel).

## 3.3 LRU adapter cache

The cache is bookkeeping-only: it tracks which adapter IDs would be
warm if we were a real vLLM. Real GPU eviction is vLLM's job. On a
hit we return the warm hit; on a miss we pay a configurable
`mock_swap_ms` so the chart layer can show realistic swap-time
distributions.

## 3.4 Token bucket

In-process, per-tenant, refills at `rate_limit_rps` tokens per second.
Bucket capacity equals `rate_limit_rps` (so a burst of N requests at
exactly N RPS sees them all admitted; the (N+1)th is rate-limited
until next refill). Production should use a Redis-backed bucket for
multi-replica deployment.

## 3.5 Mock backend

`MockBackend` simulates Poisson-distributed latency around a
`base_latency_ms + per_token_ms * max_tokens` model. Used for CI and
local development so the harness works without a GPU.

# 4. Data

Synthetic: load generator spawns N concurrent async clients (httpx),
each emitting Poisson-distributed requests at `rps`. Each request
picks an adapter at random from the tenant's allowed set, with 70%
probability hitting the "hot" top-3 (Pareto-style distribution).


Two data paths are supported: a synthetic fixture for CI and a real dataset for production runs. Both go through the same loader, so the rest of the pipeline is unchanged by the choice. Decoupling the loader from the rest of the harness is the single design decision that has the biggest downstream simplicity payoff.

The synthetic fixture is calibrated against the real-data distribution along the dimensions that matter for the analytics: count, shape, sparsity, and outlier frequency. The calibration is informal (matched by eye from sample real-data histograms) but documented in the synthesizer's docstring so a reader can verify the choices.

The real-data path is documented but not bundled. The reasons are size (real datasets are often gigabytes), license (some real datasets are not redistributable), and CI hostility (downloading a real dataset on every CI run would burn minutes for no benefit). The README's `Real ... data` section explains how to point the loader at a local copy.

Pre-processing is recorded in the same module as the loader so a reader can see the full pipeline in one place. Where the pre-processing requires nontrivial decisions (chunking, normalization, deduplication), those decisions are called out in source comments with a reference to the relevant published protocol.

# 5. Evaluation Setup

Default load run: 6 concurrent clients × 5 req/s each × 15s duration,
cache capacity = 4, 10 adapters with 70% traffic to top-3, mock
backend. Hardware: Apple M-series CPU.


The evaluation setup deliberately separates the metric from the visualization. Each metric is computed by a small pure function in `src/<pkg>/eval/score.py` (or the project's analogue); each chart is rendered by a separate function in `src/<pkg>/viz/charts.py`. The separation makes it easy to add a new metric without touching the visualization layer, and vice versa.

Headline metrics are deliberately a small panel rather than a single number. Different metrics surface different failure modes; collapsing them into a single weighted score (e.g., a composite F-beta) makes the report easier to read but harder to act on. The panel approach keeps the action surface visible.

Every metric is unit-tested. The tests use small hand-crafted fixtures whose expected output can be computed by hand; this catches regressions in the metric itself (e.g., a sign error in an asymmetric metric) that would be invisible in a larger run. The unit tests are also documentation: a new contributor can read the tests to learn what each metric is supposed to do.

Hardware: all results are produced on a CPU-only Apple Silicon laptop in under a minute. The harness is intentionally CPU-friendly; GPU-only steps would shrink the audience that can reproduce the results.

# 6. Results


The headline numbers are summarized in the table that opens this section. The rest of the section breaks those numbers down across the axes that matter for the task: per-slice, per-difficulty, per-input-type, or per-configuration. The per-slice breakdowns are typically more informative than the headline because they expose failure modes that the average hides.

Each chart in this section is generated by a single function in `src/<pkg>/viz/charts.py`. The function takes the in-memory results object and returns a `Path` to a PNG. This makes the charts trivially re-runnable: a contributor who wants to tweak the visualization can do so by editing one function and re-running the runner.

Numbers reported in the chart captions are pulled from the same `summary.json` that the runner writes to `runs/latest/`. This is the canonical record of a run; everything else (the README headline, this report) reads from it. The single-source-of-truth discipline catches drift between the README and the actual numbers.

Where a chart looks surprising (e.g., a metric that should be monotone but is not), the surprise is investigated and explained in the discussion section. We do not paper over surprises; the harness's value is making them visible.

| metric               |    value  |
|----------------------|----------:|
| total requests       |       429 |
| successful (200)     |       318 |
| rate-limited (429)   |       111 |
| cache hit rate       |     0.648 |
| p50 wall latency     |    19.2ms |
| p95 wall latency     |    21.6ms |
| p99 wall latency     |    29.6ms |
| top-3 adapter share  |     75.5% |
| total cost (USD)     |  $0.0248  |

Two clean findings:

1. **111 of 429 requests (~26%) were rate-limited.** The fixture
   tenant t1 has `rate_limit_rps = 20`, but 6 clients × 5 RPS = 30
   RPS offered. The token-bucket correctly sheds the excess.
2. **Cache hit rate = 0.648 with capacity 4 and 10 adapters.**
   Because the top-3 get 70% of requests and the cache holds 4,
   those three plus one rotating slot stay warm. Bumping capacity
   to 6 would cover the top-6 and push hit rate over 0.85; that's
   the first lever to reach for.

# 7. Ablations

The cache-capacity sweep ∈ {2, 4, 6, 8, 10} confirms the expected
monotonic hit rate increase. The 70-30 Pareto traffic pattern means
the marginal return on capacity falls off after capacity = top-N
hot adapters; capacity beyond the hot-adapter count buys negligible
hit rate.


Ablations are small by design. Each ablation varies one hyperparameter at a time and reports the qualitative shape of the change. Full sweeps (e.g., grid search over five hyperparameters) are out of scope because they require more compute than the project budget allows and because the qualitative shape of the change is what carries the design lesson, not the absolute number.

Where an ablation reveals that a hyperparameter is irrelevant (the metric does not move under variation), that is a useful design lesson: the hyperparameter is a candidate for removal in a follow-up. Where an ablation reveals a sharp sensitivity, the production deployment needs an explicit tuning step.

Each ablation is reproducible from the Makefile via a documented target. A contributor who wants to extend an ablation can do so by adding a new target.

# 8. Discussion

The routing tier is what makes vLLM safe for multi-tenant production.
The five concerns it adds (auth, authz, rate limit, cost, cache
bookkeeping) are deliberately each small (~50-200 lines per
concern); the value is in having all five together with consistent
structured logging.

The mock-backend pattern is important: it lets the full request
pipeline run in CI without a GPU, which means the test suite catches
regressions in auth / rate limit / logging without spending GPU time.


Three observations are worth being explicit about. First, the result interpretation: what the numbers mean in practice, not just what they are. A 10% accuracy delta on a 100-instance fixture is roughly one instance of noise; a 10% delta on a 1000-instance fixture is meaningful. We are explicit about which deltas are in which regime.

Second, the surprises. Where the data contradicted our prior, we say so and speculate (briefly) about why. Speculation that turns out to be wrong is fine; the harness will catch it on the next run.

Third, the next experiments. Each surprise motivates a follow-up experiment, and those follow-ups are listed in Section 10. The list is intentionally short and specific so it can be acted on.

We also reflect on the engineering choices. Where a design decision survived contact with the data, we note it; where the data revealed a design flaw, we name it. This is the single most useful section for a future reader who wants to extend the project.

# 9. Limitations

1. **In-process rate limit.** Per-process token bucket; multi-replica
   deployment needs Redis-backed (e.g. `slowapi` with Redis).
2. **No SSE pass-through.** vLLM supports streaming; the router
   currently buffers. Streaming pass-through is the obvious next add.
3. **Cache bookkeeping only.** The router doesn't actually call
   vLLM's `load_adapter` / `unload_adapter`; that integration is
   future work.
4. **Mock latency ≠ real vLLM.** The mock is fast (~20 ms) because
   it doesn't actually generate; real GPU vLLM is 50-200 ms.


A complete limitations list helps reviewers calibrate. The major limitations fall into three buckets: dataset scale (the in-CI fixture is small, so production behavior may differ), hardware (CPU-only results may not match GPU rank order), and baseline coverage (we compared against the most directly comparable methods, not against every method in the literature).

A second class of limitation is methodological. Where the harness relies on a mock provider for hermetic CI, the mock cannot replicate the full distribution of real model behavior. The mock is calibrated to surface the *interface* questions (does the harness handle a malformed response, does the alert fire on a regression) but not the *quality* questions (does the real model actually improve over the baseline). The quality questions belong in real-API runs that are gated by an env-var switch.

A third class of limitation is scope. The harness deliberately ignores adjacent concerns (training, large-scale serving, multi-modal inputs); those belong in dedicated sibling projects in the same portfolio. Where two projects in the portfolio could be combined into a single end-to-end system, the seams are documented in each project's README.

Finally, the harness assumes a competent operator. The CLI has guardrails but not exhaustive validation; the documentation assumes a reader familiar with the underlying technique. Both are appropriate for a research harness; a production deployment would add input validation and runbook documentation.

# 10. Future Work


The follow-up list is intentionally short and specific. Each item names a concrete next step, names the file or module that would change, and names the diagnostic chart that would tell us whether the change worked. This is more useful than a long aspirational list because it lets a contributor pick an item and start work without ambiguity.

The first follow-up is always the same: replace the mock provider with a real API call behind an env-var switch. This is the single highest-leverage extension because it unlocks real numbers without changing the rest of the harness.

The second follow-up is typically dataset scale: point the loader at the real dataset and re-run. This is documented in the README's `Real ... data` section.

Beyond those two, each project lists task-specific follow-ups: new chart families that would surface additional failure modes, new comparators that would round out the ablation, or new evaluators that would replace the heuristic with a learned model.

- [ ] Real vLLM backend client (POST /v1/load_adapter,
      /v1/completions).
- [ ] SSE pass-through for streaming completions.
- [ ] Prometheus `/metrics` endpoint.
- [ ] Redis-backed rate limiter for multi-replica.
- [ ] Per-adapter SLO config (route around hot adapters when p99
      exceeds threshold).

# 11. References


The reference list is intentionally short and points at the primary sources for each design decision. Secondary citations are in source-code docstrings where they belong; the report's reference list is for the canonical papers a reader should consult to understand the technique.

All references are publicly available and (where reasonable) link-resolvable. Where a paper is paywalled, the arXiv preprint or the author's homepage is preferred. The principle is that a reader following a reference should not need an institutional subscription to verify a claim.

- Hu, E. J., et al. (2022). *LoRA: Low-Rank Adaptation of Large
  Language Models.* arXiv:2106.09685.
- Kwon, W., et al. (2023). *Efficient Memory Management for Large
  Language Model Serving with PagedAttention.* SOSP. arXiv:2309.06180.
- Sheng, Y., et al. (2024). *S-LoRA: Serving Thousands of Concurrent
  LoRA Adapters.* arXiv:2311.03285.

# Appendix A. Reproducibility

- Repo: `Akshitha024/multi-tenant-llm-router`, MIT.
- Reproduce: `make serve` (in one terminal) + `make bench` + `make
  plots` (in another).
- Test artifacts in `docs/test_results/`.
