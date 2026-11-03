---
term: eval.runs
aliases: [runs, dry, budget, cost, estimate, resources, retry, limit]
description: nock eval run: a dry run's reasons, a budget, resource limits, retrying the failed
---

`.nock/nock eval run [TARGETS…]`: the default target, or outputs and rule names. `--dry` lists each job: from cache, or compute and why. `--budget USD` refuses an estimate past it (each rule's mean past cost.json, else `resources: estimate_cents=N`). A rule takes `resources: stacks=1`; the profile's `resources`, or `--limit stacks=6`, caps them. `--retry` computes the failed again. Rerun to resume.
