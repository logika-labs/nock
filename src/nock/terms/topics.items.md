---
term: topics.items
aliases: [item, items, submit, files, derived, screenshot, screenshots, asset, assets, description]
description: An item: a title, a description, and one decision or asset
---

`.nock/nock items create TOPIC '{"title": "Checkout email", "description": "The receipt after a paid order", …}'`: a short title, the details in `description`. Then one decision (`docs topics.decisions`) with the project `files` it concerns, or one asset: a project file or a `derived` file (`docs topics.derived`), or its variants (`docs topics.variants`). Bare: no notes. Ref: `topic/slug`. Move: `items update REF '{"topic": T}'`.
