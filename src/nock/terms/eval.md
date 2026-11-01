---
term: eval
aliases: [evals, evaluation, evaluations, snakemake]
description: nock eval: a Snakemake workflow per scenario, cached by content, read with SQL
---

An evaluation is `evals/NAME/Snakefile`: rules are steps, wildcards parameters. `.nock/nock eval init NAME` scaffolds it with nock's profile; `eval run` runs Snakemake, restoring from `cache/` (committed) every output whose code, params and inputs match one computed anywhere; `eval query`, `show` and `compare` read the result files with DuckDB, as does the studio's Evals tab. Comparisons are never rules. Snakemake and DuckDB run through uv.
