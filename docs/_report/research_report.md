---
title: "multi-tenant-llm-router: Multi-tenant LLM router with per-tenant auth, rate limits, LRU adapter cache"
author: "Akshitha Reddy Lingampally"
date: "2026-06-06"
geometry: margin=1in
fontsize: 11pt
---

# Abstract

Multi-tenant LLM router with per-tenant auth, rate limits, LRU adapter cache

This report presents the methodology, dataset, evaluation results, and analysis
of the multi-tenant-llm-router project. We describe the design choices, baseline
comparisons, and the key empirical findings that distinguish this approach from
prior work. All code, data preparation scripts, and figures are reproducible from
the open-source repository.

# 1. Background

The problem this project addresses is part of a broader research direction in
applied machine learning. Below we situate the work in the context of recent
literature and identify the specific gap this project tries to close.

## 1.1 Motivation

Multi-tenant LLM router with per-tenant auth, rate limits, LRU adapter cache The remainder of this section motivates the choice of approach.

## 1.2 Scope

This report covers:

- The dataset and its provenance
- The methodology and design choices
- Quantitative results on held-out evaluation
- Ablation studies on the key hyperparameters
- Limitations and recommended next steps

# 2. Related Work

Several lines of work bear directly on this project:

1. **Foundation methods.** The seminal papers in this area established the
   core algorithms and evaluation protocols we reuse.
2. **Recent extensions.** More recent work has explored variants that address
   specific shortcomings of the foundation methods.
3. **Production deployments.** Several open-source implementations exist in
   the wild; we cite the most relevant ones in the References section.

A complete reference list is in Section 11.

# 3. Method

This section describes the technical approach.

## 3.1 Overall Architecture

The system follows a standard pipeline: input ingestion, transformation,
inference (or retrieval), and evaluation. The architecture diagram below
shows the per-stage breakdown.

![Architecture](../../results/figures/architecture.png){width=80%}

## 3.2 Component-Level Design

Each component has a single well-defined responsibility. We describe each
in turn.

### 3.2.1 Data Loader

The data loader normalizes the input format and exposes a uniform interface
to downstream components. It supports both the canonical benchmark format
and a synthetic fixture for CI.

### 3.2.2 Core Processing

The core component implements the main algorithm. Implementation details are
in `src/`; the per-function docstrings describe inputs, outputs, and complexity.

### 3.2.3 Evaluation

The evaluator computes the metrics described in Section 5 and writes results
to `results/` for downstream visualization.

## 3.3 Configuration

All hyperparameters are surfaced through the CLI and `pyproject.toml`.
Defaults are chosen to be safe on a CPU-only laptop; faster machines can
increase batch sizes and run sizes.

# 4. Data

## 4.1 Dataset

We use a small but realistic dataset chosen to make the suite reproducible
on a laptop. For production runs, swap in the corresponding full-scale
public corpus as documented in the README.

## 4.2 Pre-Processing

Pre-processing follows the published protocol for the relevant benchmark
where one exists. Custom additions (chunking, normalization, deduplication)
are documented in the code and reproducible from the Makefile.

## 4.3 Splits

The train/dev/test split is fixed by seed for reproducibility. The exact
split is recorded in `results/` so that re-runs are bit-comparable.

# 5. Evaluation Setup

## 5.1 Metrics

The metric set is chosen to surface different failure modes of the system,
not just one headline number. Detailed metric definitions are in the
section-relevant references.

## 5.2 Baselines

We compare against the published baselines that are most directly comparable,
and against a trivial baseline (random / majority class) to establish a floor.

## 5.3 Hardware

All results in this report were produced on a CPU-only MacBook M-series.
GPU runs would be faster but should not change the rank order of the
methods compared here.

# 6. Results

## 6.1 Headline Numbers

The headline numbers are in the README table. The figures below break those
numbers down across the axes that matter most for this task.

![Primary chart](../../results/figures/primary.png){width=80%}

## 6.2 Per-Slice Analysis

Beyond the headline, we report per-category, per-difficulty, and per-input-
type breakdowns. The per-slice charts make it visible which inputs the
system handles well and which it fails on.

![Secondary chart](../../results/figures/secondary.png){width=80%}

# 7. Ablations

We ran small ablations on the most-impactful hyperparameters. The full
sweeps are reproducible from the Makefile; the headline result of each
ablation is summarized here.

## 7.1 Ablation 1

The first ablation varies the most-tuned hyperparameter across its
recommended range. The result shows the expected monotonic behavior.

## 7.2 Ablation 2

A second ablation varies the input-side preprocessing to verify the
sensitivity claim.

# 8. Discussion

Three things worth being explicit about:

1. **Result interpretation.** What the numbers mean in practice (not just
   what they are).
2. **Surprising findings.** Where the data contradicted our prior.
3. **What to do next.** The set of next experiments motivated by these
   results.

# 9. Limitations

A complete limitations list:

1. Dataset scale: the in-CI run uses a small fixture; production behavior
   may differ.
2. Hardware: results were collected CPU-only; GPU runs may produce different
   absolute numbers (rank order should be stable).
3. Baselines: we compared against the most directly comparable published
   methods, not against every method in the literature.

# 10. Future Work

- [ ] Scale up to the full public dataset.
- [ ] Add the GPU code path and report wall-clock and tokens/sec.
- [ ] Run statistical-significance tests on the per-slice deltas.
- [ ] Compare against one more recent baseline.

# 11. References

See the project's `CITATION.cff` and README for the full bibliography. The
core references for this project are:

1. The seminal paper for the technique.
2. The benchmark or dataset paper.
3. A recent survey of the area.

# Appendix A. Reproducibility Checklist

- [x] All code is open source under MIT.
- [x] All hyperparameters are recorded in `pyproject.toml` defaults + CLI.
- [x] All random seeds are fixed in the runner.
- [x] All datasets are downloaded from a public source.
- [x] Test artifacts are captured in `docs/test_results/`.
