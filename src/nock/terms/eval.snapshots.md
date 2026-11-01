---
term: eval.snapshots
aliases: [snapshot, snapshots, eval-cache, stale, provenance, clone]
description: An output is cached by provenance: its code, params, inputs' content and the steps before
---

Snakemake names each cache entry by a hash of the rule's script, its params, its input files' content and the hashes of the jobs before it. A fresh clone has no results/, so a run restores every match from `cache/` and computes the rest; mtimes never decide. An output is stale when a run would compute it again: `eval show` says why in Snakemake's words. Code a script imports is not hashed: make it an input or a param.
