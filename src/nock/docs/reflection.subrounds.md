---
term: reflection.subrounds
aliases: [subrounds, subround, round.toml, kinds, stop-guard]
description: "A subround is a folder: round.toml, agents/, material.py; its lead's brief a term of its name"
---

`rounds/<round>/<subround>/`: `round.toml` (`[due]`, `[material.NAME]`, `[lead]`, `[[agents]]`, `[end]` checks, commit, kinds), `agents/NAME.md`, `material.py` for material no command gives; the lead's brief is `docs/briefs/<round>.<subround>.md`. `.nock/rounds/` adds or overrides by name, briefs in `.nock/docs/briefs/`. A session that started a run cannot end its turn while it is open: nock refuses the stop once, but not while background agents run.
