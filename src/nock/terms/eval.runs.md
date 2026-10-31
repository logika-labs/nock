---
term: eval.runs
aliases: [runs, dry, budget, resume]
description: nock eval run: compute what an assignment needs, in parallel, resumable, within a budget
---

`.nock/nock eval run 'ASSIGNMENT'` runs up to `--parallel` steps at once (4), never recomputing a snapshot that exists; run it again to resume. `--dry` prints the tree, what is reused and computed, and the time and cost estimated from earlier snapshots (else a step's `estimate`). `budget_usd` stops starting steps once spent plus estimated would pass it. `runs/ID/run.json` keeps commit, assignment, outcomes, time, cost. Another machine is another checkout: run part, commit, push.
