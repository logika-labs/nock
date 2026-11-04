---
term: decisions.edit
aliases: [edit, rework, list, show, delete, batch]
description: nock decisions list, show, edit, delete and batch
---

`.nock/nock decisions list '{"path": "src/billing.py"}'` (or `"tag"`, `"status"`, `"review"`) lists the decisions governing a file, or filtered; `decisions show 7` one in full; `decisions edit '{"number": 7, …}'` reworks one, marks a todo done, sets `superseded_by` (null: it stands again), each a commit; `decisions delete 7` removes one that should not have been recorded; `decisions batch '{"edit": […], "delete": […]}'` does many in one commit.
