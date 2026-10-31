---
term: tools.retiring
aliases: [archive, retire, pinned]
description: Retired tools go to .nock/tools/archive/; pinned=True keeps one
---

A tool nobody uses, or the project outgrew, is retired: `git mv` it into `.nock/tools/archive/`, which is kept but never loaded, so a later round can bring it back. `@nock.command(pinned=True)` marks a tool rarely used but vital: it is never a retire candidate.
