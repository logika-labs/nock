---
term: review
aliases: [item, items, screenshot, screenshots, video, pdf]
description: Show the owner what you made: nock review add
---

A screenshot, video, PDF, HTML page or text you made for the owner to look at, an item under review: `.nock/nock review add '{"key": "email/report", "title": …, "files": [PATHS] or "text": …, "note": …, "recipe": {…}}'`. The same key again is the next version; title, tags and recipe carry over. Committed on the main checkout (files over 20 MB stay local). `review list`, `review show KEY` (every version, each file's path). The owner judges it in `.nock/nock studio`.
