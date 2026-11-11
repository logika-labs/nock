---
term: checks.chains
aliases: [chain, chains, concurrency]
description: Checks run side by side; a chain's checks one after another
---

Checks run side by side. Those that must not (a shared build, lock or cache) share a `chain = "rust"`, and run in the order written. `.nock/nock check rust` runs a chain, `.nock/nock check NAME` one check. At most two check runs go at once, machine-wide, so parallel sessions don't pile up test suites.
