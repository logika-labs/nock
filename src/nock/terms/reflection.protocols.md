---
term: reflection.protocols
aliases: [protocols, round.toml, kinds, stop-guard]
description: A protocol is a folder: round.toml, lead.md, agents/, material.py
---

`rounds/<namespace>/<protocol>/`: `round.toml` (who it is for, `[due]`, `[material.NAME]` from python, command, topic or git, `[lead]`, `[[agents]]`, `[end]` checks, commit, kinds), `lead.md`, `agents/NAME.md`, and `material.py` only for material no command gives. nock ships some; `.nock/rounds/` adds or overrides by name. A session that started a round cannot end its turn while it is open: nock refuses the stop once, saying what it still needs, but not while background parts run.
