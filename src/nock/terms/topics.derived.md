---
term: topics.derived
aliases: [from, recipe, regenerate, video, captions, poster, gif]
description: A derived file: made to show part of the project, and how to make it again
---

A derived file in an asset's `assets.json`: `{"kind": "derived", "name": "shot.png"}`, the file beside it, with `from` (the project files it shows), `when` (the case it shows), `recipe` (`{"command": …}` and/or `{"instruction": …}`). Images (a GIF animates), videos, PDFs, HTML and text show in the studio; all but small text go to `.nock/shared/media/`. A video takes `captions` (WebVTT) and a `poster`, named beside it. New version: run the recipe, then write the asset's `versions/next/`.
