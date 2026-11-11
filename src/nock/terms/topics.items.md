---
term: topics.items
aliases: [item, items, submit, derived, screenshot, screenshots, asset, assets, description]
description: An item is a decision, with the assets that show it
---

A decision (`docs topics.decisions`) with the assets that show it, in `topics/T/decisions/SLUG/`: `events/x.json` `{"kind": "created", "title": "…", "description": "…"}` and `versions/next/decision.json`. Each asset (a screenshot, a project file, a page) in `assets/NAME/`: its `created` event and `versions/next/assets.json` with its file beside it (`docs files.asset`). A file to review with no choice in it gets a plain "Review: …" decision. Ref: `topic/slug`; move it with a `moved` event.
