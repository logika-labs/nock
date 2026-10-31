---
term: eval.compare
aliases: [comparison, bootstrap, interval]
description: nock eval compare: leaves grouped by one parameter, the rest fixed, with intervals
---

`.nock/nock eval compare '{"by": "arm", "metric": "detected"}'` groups the last step's current snapshots by `arm`, holding the other parameters fixed and pooling `rep` (`over` names others): n, mean, a bootstrap 95-in-100 interval, the difference from the baseline (paired when the units match) and the runs behind. `unit: "bug"` averages per bug first and resamples bugs; `where` narrows; `step` compares another step.
