---
term: eval.determinism
aliases: [determinism, seeds, reproducible]
description: Fix the inputs: traffic, seeds, data; repetition is a parameter
---

What varies between runs must be a parameter or noise you measure. Fix the inputs: recorded traffic, seeds, data snapshots, the model as a parameter. Make repetition explicit, `"rep": {"values": [1, 2, 3]}`, so each repetition is its own snapshot and more can be added later. A step that reads the clock or the network makes its snapshot a sample, not a fact.
