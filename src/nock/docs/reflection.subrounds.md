---
term: reflection.subrounds
aliases: [subrounds, subround, round.toml, kinds, stop-guard]
description: A subround is a folder: round.toml, lead.md, agents/, material.py
---

`rounds/<round>/<subround>/`: `round.toml` (who it is for, `[due]`, `[material.NAME]` from python, command, git or the earlier records, `[lead]`, `[[agents]]`, `[end]` checks, commit, kinds), `lead.md`, `agents/NAME.md`, and `material.py` only for material no command gives. nock ships some; `.nock/rounds/` adds or overrides by name. A session that started a run cannot end its turn while it is open: nock refuses the stop once, saying what it still needs, but not while background agents run.
