---
term: decisions.record
aliases: [fields, alternatives, touches, supersedes]
description: A decision's fields, written for someone who doesn't know the code
---

`title`; `status`: done, todo or question; `summary`, for someone who knows what the system does but not how it is built; `evidence`; `alternatives`, `[{"option": …, "why_not": …}]`, only those really weighed; `tags`; `touches`, the files or globs it governs (`decide` says when one matches nothing); `supersedes`, the decisions it overturns, which stay as history.
