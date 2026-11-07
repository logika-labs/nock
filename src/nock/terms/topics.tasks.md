---
term: topics.tasks
aliases: [task, tasks, progress, dispatch]
description: A task item: dispatched work, its state kept current
---

`items create TOPIC '{"title": …, "task": {"brief": …, "branch": …, "worktree": …}}'` when work is dispatched. Its state: queued, running, waiting (`"waiting_on": "owner"` or a task's ref), done, failed: `items update REF '{"state": "running"}'`. Post progress with `--reply`; every update is its last word, and the studio shows long silence amber. Done accepts it (the thread keeps the report, the merge commit); failed stays open for the owner.
