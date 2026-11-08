---
term: topics.state
aliases: [progress, done, abandoned, planned, active, dispatch, task, tasks, topic-status]
description: A topic's state and status: where its work stands, kept current as you work
---

`state`: planned, active (a new topic's), done, abandoned; `status`: where the work is, in a line. `topics update TOPIC '{"state": "active", "status": "eval running, about 2 h"}'`, or the status alone: when you start, at each milestone; done or abandoned when finished. A state change without a status clears it. Each change is a status entry in its thread. Dispatched work lives here too. `topics list --state active`.
