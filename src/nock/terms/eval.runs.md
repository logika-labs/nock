---
term: eval.runs
aliases: [runs, dry, budget, cost, estimate, resources]
description: nock eval run: a dry run's reasons, a budget from past cost.json, Snakemake with the profile
---

`.nock/nock eval run [TARGETS…]` runs the default target, or output paths and rule names. `--dry` lists each job: from cache, or compute and Snakemake's reason (code, params, inputs changed). `--budget USD` refuses to start when the jobs to compute, at each rule's mean past cost.json (else its `resources: estimate_cents=N`), would cost more. Limit concurrency with `resources: agents=1` and the profile's `resources`. Rerun to resume.
