---
term: files.review
aliases: [files.blocks]
description: A topic's review: versions/next/review.json, its blocks, its html files
---

`topics/orders/review/versions/next/review.json`, html files beside it:

    {"summary": "Orders moved to SQLite", "blocks": [
      {"kind": "text", "text": "markdown"}, {"kind": "item", "item": "sqlite"},
      {"kind": "diff", "asset": "schema", "from": 1, "to": 2},
      {"kind": "html", "file": "flow.html", "height": 320}]}

Kinds: text, item, diff, doc, excerpt (`lines`), image, table, chart, html (`nock docs review`). A new version replaces it.
