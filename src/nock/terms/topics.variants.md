---
term: topics.variants
aliases: [variant, variants, prefer, preferred]
description: Variants: several takes on one asset, of which the owner prefers one
---

`"variants": true` in an asset version's `assets.json`, with several files of one type (three takes on one picture), makes them variants of that asset. The card shows the preferred one, else the first; the owner stars one in the viewer (a `preferred` event in the asset's `events/`), and accepts the decision only once each asset with variants has one preferred. Never unrelated files: those are assets of their own. Lay them out with a view (`docs topics.views`).
