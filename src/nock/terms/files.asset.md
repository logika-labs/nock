---
term: files.asset
aliases: [files.version, files.variants]
description: A decision's asset: a screenshot, file or page, versioned before and after
---

`decisions/sqlite/assets/receipt/`: `events/x.json` {"kind": "created", "title": "Receipt"}, then `versions/next/assets.json` with the file beside it:

    {"files": [{"kind": "derived", "name": "shot.png", "from": ["app.py"], "recipe": {"command": "make shot"}}]}
    {"files": [{"kind": "project", "path": "src/app.py"}]}

Before and after are versions 1 and 2. Variants: `"variants": true`, several files, and a `preferred` event {"version", "name"} before the decision is accepted.
