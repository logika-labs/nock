---
term: reflection.record
aliases: [reflect-submit, verdicts, expectations]
description: reflect --submit: the round's changes, expectations and verdicts
---

`.nock/nock reflect --submit '{"protocol": …, "summary": …, "changes": [{"kind", "target", "why", "expect"}], "verdicts": [{"expectation", "held", "evidence"}], "notes": …}'`. The kinds are the protocol's (`[end] kinds`). `held` is true, false, or null for too early. It requires the lead's files, runs the end checks, refusing while one fails, keeps the record in `.nock/shared/rounds/<protocol>/<date>/` and commits it with the protocol's paths.
