---
term: eval.determinism
aliases: [determinism, seeds, reproducible]
description: Fix the inputs: traffic, seeds, data; repetition is a wildcard
---

What varies between runs must be a wildcard or noise you measure. Fix the inputs: recorded traffic, seeds, data snapshots, the model as a wildcard. Make repetition explicit, `rep` in the output path with `REPS = [1, 2, 3]`, so each repetition is its own cached output and more can be added later. A step that reads the clock or the network makes its output a sample, not a fact.
