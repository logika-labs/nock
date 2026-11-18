---
term: files.asset
aliases: [files.version]
description: A topic's asset: a file, versioned, so two versions compare
---

`topics/orders/assets/schema/`: `events/x.json` {"kind": "created", "title": "The orders schema"}, then `versions/next/asset.json` with the file beside it:

    {"file": {"kind": "project", "path": "src/schema.sql"}}
    {"file": {"kind": "derived", "name": "receipt.png", "from": ["app.py"], "recipe": {"command": "make shot"}}}

Before and after are versions 1 and 2: the review shows them as a diff. Also `titled`.
