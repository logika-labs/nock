---
term: decisions.tags
aliases: [tag, tags]
description: The fixed tags and your own; near-duplicates merged
---

A project may fix its tags (`decisions.tags` in `.nock/config.toml`; `decide --help` lists them): any other is refused. Always allowed: `important` (the owner's call), and `logika` and `instrumentation` (a logika round's). Unfixed, tags are `technical`, `product`, `improvement` and your own, lowercase; `decide` prints the new ones, so a near-duplicate is fixed while cheap. A round merges tags that mean the same.
