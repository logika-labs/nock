---
term: topics.views
aliases: [view, views, layout, sizes]
description: A view: an HTML page laying out an asset's variants, with nock's look
---

A view is an HTML file beside an asset's files, named in its `assets.json`: `"views": [{"name": "sizes.html", "title": "At three sizes"}]`. The studio shows it as a tab of the viewer, with nock's styles (`label`, `grid`, `row`, `card`, `caption`, `checker`, `dark`, `pixels`) and `window.nock.assets` (name, type, address, preferred). Reach the files by name: `<img src="a.svg">`. Each favicon at 16, 32 and 64 px is a view.
