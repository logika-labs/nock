---
term: tools.caching
aliases: [cache, cached, fresh]
description: cache= replays the last result while its files are unchanged
---

`@nock.command(cache="src/** tests/**")`: a call with the same arguments replays the last result while the files those globs match and the tool's own code are unchanged, with a note saying so. `--fresh` runs it anyway. Only for a tool whose result depends on nothing else.
