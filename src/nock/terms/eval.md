---
term: eval
aliases: [evals, evaluation, evaluations, snakemake]
description: nock eval: a Snakemake workflow per scenario, cached by content, read with SQL
---

An evaluation is `evals/NAME/Snakefile`: rules are steps, wildcards parameters. `.nock/nock eval init NAME` scaffolds it; `eval run` runs Snakemake, restoring from the cache every output whose code, params and inputs match one computed anywhere. The cache is `cache/`, committed, or with `[eval] cache = DIR` in .nock/config.toml `DIR/NAME`, outside git. `eval query`, `show` and `compare` read the results with DuckDB; the studio draws the scenario as an experiment (`eval.experiments`).
