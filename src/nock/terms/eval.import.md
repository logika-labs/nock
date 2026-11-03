---
term: eval.import
aliases: [import, importing, migrate]
description: nock eval import: put outputs computed elsewhere into the cache, so a run restores them
---

`.nock/nock eval import FILE`, `{"outputs": [{"output": "results/RULE/…", "source": DIR, "metrics": {…}, "cost": {"usd": …}}], "targets": […]}`: each output's files cloned from its source (never moved) into the cache entry its job would have, so a run restores it. `"error"` imports a failed one. Jobs after a checkpoint are known once it is restored: import in rounds.
