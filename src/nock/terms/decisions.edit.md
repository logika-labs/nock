---
term: decisions.edit
aliases: [edit, rework, list, show]
description: nock decisions list, show and edit
---

`.nock/nock decisions list '{"path": "src/billing.py"}'` (or `"tag"`, `"status"`, `"review"`) lists the decisions governing a file, or filtered; `decisions show 7` one in full; `decisions edit '{"number": 7, …}'` reworks a rejected one, marks a todo done, or merges tags, in place (git keeps the history). The first time a session edits a file a standing decision touches, it is shown, the rejected first.
