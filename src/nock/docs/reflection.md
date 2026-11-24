---
term: reflection
aliases: [reflect, round, rounds]
description: "Rounds and their subrounds: judge and improve the project, a subround each in its own agent"
---

A round is a group (audit, fuzz, logika, nock); a subround one part of it (`audit.security`; `reflection.subrounds`). `.nock/nock reflect` lists the subrounds: on here, due and why, the last run. `reflect ROUND` prints the plan: one subagent per subround on here, each running `reflect ROUND.SUBROUND`, which starts it and prints its lead's brief, agents and files; `reflect --submit JSON` records it. Fit runs first and sets the others up.
