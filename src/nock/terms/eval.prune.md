---
term: eval.prune
aliases: [prune, pruning]
description: nock eval prune: delete stale and failed snapshots; runs keep their numbers
---

`.nock/nock eval prune [SCENARIO] --dry` lists the stale and failed snapshots with why; without `--dry` it deletes them and their artefacts. Runs keep their own summary numbers, so history stays readable. A failed snapshot is a result until pruned: a run reuses it rather than retry, so prune to retry after fixing the machine.
