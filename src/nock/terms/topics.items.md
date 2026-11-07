---
term: topics.items
aliases: [item, items, submit, files, derived, screenshot, screenshots]
description: An item: a title, and a decision, project files or derived files
---

`.nock/nock items create TOPIC '{"title": …, "decision": {…}, "files": [PATHS], "derived": […]}'`, one or more of: a decision (`docs topics.decisions`); project `files`, repository paths copied as they are now; `derived` files made to show part of the project (`docs topics.derived`); or a `task` (`docs topics.tasks`). Bare: no notes; say more in the thread only when asked. Its ref is `topic/slug` (the slug from the title, or `"slug"`). Move: `items update REF '{"topic": T}'`.
