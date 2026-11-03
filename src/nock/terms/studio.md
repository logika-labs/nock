---
term: studio
aliases: [page, web, owner-page]
description: nock studio: the owner's local page
---

`.nock/nock studio` (with `'{"open": true}'` or `'{"port": N}'`) serves the owner's page on 127.0.0.1 until stopped. Its Decisions tab reviews decisions and questions in place: accept, reject, note, elaborate; `#7` opens decision 7. Its Evals tab draws each scenario as a graph of its runs (hover, narrow, what if, live, comparisons; words in `evals/NAME/studio.json`), never running a step. It is the owner's: an agent starts it only when asked.
