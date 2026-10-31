---
term: reflection.record
aliases: [finish, verdicts, expectations]
description: reflect finish: the round's changes, expectations and verdicts
---

`.nock/nock reflect finish '{"summary": …, "changes": [{"kind", "target", "why", "expect"}], "verdicts": [{"expectation", "held", "evidence"}], "notes": …}'`. Kinds: add, change, retire, check, generator, other. `held` is true, false, or null for too early. It requires `report.md` and `share.md`, runs `nock-tools`, `nock-generators`, `nock-map` and `nock-share`, refusing while one fails, and commits `.nock/`.
