---
term: checks.changed
aliases: [paths, focus, affected]
description: check --changed runs only the checks the branch's changes affect
---

`.nock/nock check --changed` runs the checks that the paths changed since the main branch (committed or not) can affect. `paths = ["src/**", "!src/web/**"]` in `[checks.NAME]` says which (the last glob that matches wins); none means every change. A change no check names runs them all, unless `checks.unaffected` lists it. `focus = ["tests/**/test_*.py"]`: when all its changes fit, they are appended to the command. Plain `check` is the full gate.
