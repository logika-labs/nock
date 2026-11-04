---
term: assets
aliases: [asset, screenshot, screenshots, video, pdf]
description: Show the owner what you made: nock assets add
---

A screenshot, video, PDF, HTML page or text you made for the owner to look at: `.nock/nock assets add '{"key": "email/report", "title": …, "files": [PATHS] or "text": …, "note": …, "recipe": {…}}'`. The same key again is the next version; title, tags and recipe carry over. Committed on the main checkout (files over 20 MB stay local). `assets list`, `assets show KEY` (every version, each file's path). The owner reviews it in `.nock/nock studio`.
