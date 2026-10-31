---
term: consult
aliases: [consultation, consultant]
description: Consult before you change code: advice on the decisions, tools and checks that bear
---

`.nock/nock consult '{"intent": "Move orders to Postgres.", "context": "SQLite locks under load."}'`: a fresh agent reads the decisions, map, tools and checks, changes nothing, and advises in a few lines: what to keep to, the tools for its steps, what to record, the checks and docs to read. You wait (`consult.deadline`, 600s), then do as it says or record why not. Off with `consult.enabled = false`.
