---
term: reflection.record
aliases: [reflect-submit, verdicts, expectations]
description: "reflect --submit: a run's changes, expectations and verdicts"
---

`.nock/nock reflect --submit '{"subround": …, "summary": …, "changes": [{"kind", "target", "why", "expect"}], "verdicts": [{"expectation", "held", "evidence"}], "notes": …}'`. The kinds are the subround's (`[end] kinds`). `held` is true, false, or null for too early. It requires the lead's files, runs the end checks (refusing while one fails), and commits the record (`.nock/shared/rounds/`) with the subround's paths. Then the lead reports the subround in its final message.
