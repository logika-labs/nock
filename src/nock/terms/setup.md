---
term: setup
aliases: [init, upgrade, install, primer, wiring]
description: nock init and nock upgrade: installing, re-wiring, upgrading
---

`nock init` vendors nock into `.nock/core/`, writes the shim, `config.toml`, `tools/`, the primer `.nock/context.md` (imported into CLAUDE.md), wires Claude Code's hooks and permissions (`permissions`), and installs the skills and subagents; run again, it re-wires. `.nock/nock upgrade` merges the latest release into the core, keeping local edits (a three-way merge), then re-runs init; a session start does when the merge is clean (`upgrade.auto`). `nock-wiring` fails while the wiring is stale.
