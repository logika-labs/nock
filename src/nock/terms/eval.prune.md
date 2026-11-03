---
term: eval.prune
aliases: [prune, pruning]
description: nock eval prune: delete stale and failed cache entries, so a run computes them again
---

`.nock/nock eval prune [SCENARIO] --dry` lists the cache entries no current output of the default target is, and the failed with what was computed from them (keyed by provenance, they would come back unchanged); without `--dry` it deletes them. A failed output is a result, restored rather than retried: `eval run --retry` computes it again, keeping its attempt for its step (`step.previous`).
