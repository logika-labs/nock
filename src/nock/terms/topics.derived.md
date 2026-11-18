---
term: topics.derived
aliases: [from, recipe, regenerate, video, captions, poster, gif, derived]
description: A derived file: made to show part of the project, and how to make it again
---

A derived file in an asset's `asset.json`: `{"file": {"kind": "derived", "name": "shot.png", …}}`, the file beside it, with `from` (the project files it shows), `when` (the case it shows), `recipe` (`{"command": …}` and/or `{"instruction": …}`). Images, videos, PDFs, HTML and text show in the studio; all but small text go to `.nock/shared/media/`. A video takes `captions` (WebVTT) and a `poster` beside it. New version: run the recipe, write `versions/next/`.
