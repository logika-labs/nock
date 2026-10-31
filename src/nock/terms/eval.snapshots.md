---
term: eval.snapshots
aliases: [snapshot, snapshots, stale, identity]
description: The state after a step for one set of values, named by a hash of its identity
---

`snapshots/HASH/snapshot.json`: step, parameters read so far, digests of those values' files and of the steps' code, results, cost, time and the artefact manifest. Identity is content, not commits: any digest that changes makes the snapshot stale, kept and marked, and a run computes a fresh one beside it. The snapshot before a fork is whole, since every branch resumes from it; so is every other.
