---
term: files.media
aliases: []
description: media/: pictures, videos and other non-text files, by sha256
---

`.nock/shared/media/<sha256>`: every file in a version that isn't small text, and every attachment, kept by its content and named in `assets.json` or the message. The project commits the folder, puts it under git LFS (`media/** filter=lfs diff=lfs merge=lfs -text` in `.gitattributes`) or ignores it; a missing file shows by name and is made again by its recipe.
