---
term: eval.prune
aliases: [prune, pruning]
description: nock eval prune: delete stale and failed cache entries, so a run computes them again
---

`.nock/nock eval prune [SCENARIO] --dry` lists the cache entries no current output of the default target is, and the failed ones with what was computed from them (the cache keys provenance, not content, so those would come back unchanged); without `--dry` it deletes them and their links. A failed output is a result until pruned: a run restores it rather than retry, so prune to retry after fixing the machine.
