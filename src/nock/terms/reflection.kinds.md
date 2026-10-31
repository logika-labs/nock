---
term: reflection.kinds
aliases: [kinds, round-kinds, stop-guard]
description: Kinds of round: `nock reflect [KIND]` starts one, `… finish JSON` ends it
---

`.nock/nock reflect` starts nock's own round; `.nock/nock reflect logika` a logika round, in a Logika project. Each kind finishes with `.nock/nock reflect [KIND] finish JSON`, which requires its files and runs its checks. A turn of the session that started a round cannot end while it is open: nock refuses the stop once, naming the kind and what it still needs. A kind is an entry in `kinds.KINDS` and a skill; `finish` is never a kind's name.
