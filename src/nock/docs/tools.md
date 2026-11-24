---
term: tools
aliases: [tool, command, commands]
description: A tool: a decorated function in .nock/tools/, live on its next call
---

A tool is a function decorated with `@nock.command` in any module under `.nock/tools/` (a file per area is good). It is live on the next call, with nothing to register: `.nock/nock NAME` runs it, `.nock/nock` lists the toolbox. Its name is the function's, `_` → `-` (or `name=`); `group="db"` makes it `.nock/nock db NAME`. The docstring's first line is its summary wherever it is listed; the rest is its `--help`. A name that clashes is a load failure, never an override.
