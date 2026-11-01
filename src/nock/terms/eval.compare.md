---
term: eval.compare
aliases: [comparison, bootstrap, interval]
description: nock eval compare: a rule's outputs grouped by one parameter, the rest fixed, with intervals
---

`.nock/nock eval compare '{"by": "arm", "metric": "detected", "step": "detect"}'` groups the rule's current outputs by `arm`, holding the other wildcards fixed and pooling `rep` (`over` names others): n, mean, a bootstrap 95-in-100 interval, and the difference from the baseline, paired when both sides have the same units. `unit: "bug"` averages per bug first and resamples bugs; `where` narrows; `step` is needed when several rules have metrics.
