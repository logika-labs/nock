---
term: decisions.edit
aliases: [edit, rework, list, show, delete]
description: nock decisions list, show, edit and delete
---

`.nock/nock decisions list '{"path": "src/billing.py"}'` (or `"tag"`, `"status"`, `"review"`) lists the decisions governing a file, or filtered; `decisions show 7` one in full; `decisions edit '{"number": 7, …}'` reworks a rejected one, marks a todo done, or merges tags, in place (git keeps the history); `decisions delete 7` removes one that should not have been recorded. The first time a session edits a file a standing decision touches, it is shown, the rejected first.
