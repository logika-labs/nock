---
term: topics.items
aliases: [item, items, submit, files, derived, screenshot, screenshots]
description: An item: a title and one asset, a decision, a project file or a derived file
---

`.nock/nock items create TOPIC '{"title": …, "decision": {…}}'`, one asset per item: a decision (`docs topics.decisions`), with the project `files` it concerns; one project file; one `derived` file (`docs topics.derived`); or a `task` (`docs topics.tasks`). Several files go in several items; variants of one are options (`docs topics.options`). Bare: no notes. Its ref is `topic/slug`. Move: `items update REF '{"topic": T}'`.
