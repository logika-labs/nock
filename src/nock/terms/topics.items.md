---
term: topics.items
aliases: [item, items, submit, derived, screenshot, screenshots, asset, assets, description]
description: An item is a decision, with the assets that show it
---

`.nock/nock items create TOPIC '{"title": "Checkout email", "description": "The receipt after a paid order", …}'`: a decision (`docs topics.decisions`) with the assets that show it: each project file in `files`, the `derived` file (`docs topics.derived`) or its variants (`docs topics.variants`). A file to review with no choice in it gets a plain "Review: …" decision. Before and after are versions of one asset. Ref: `topic/slug`. Move: `items update REF '{"topic": T}'`.
