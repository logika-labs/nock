---
term: tools.loading
aliases: [imports, load, load-failure]
description: Every call loads the whole toolbox: keep top-level imports light
---

Every call and every hook imports every module in `.nock/tools/` (subdirectories such as `archive/` are skipped). Keep a module's top-level imports light, and import heavy packages inside the tool that needs them. A module that fails to import is a load failure, printed with its `file:line` on every call; the other tools keep working.
