---
term: setup
aliases: [init, upgrade, install, primer, wiring]
description: nock init and nock upgrade: installing, re-wiring, upgrading
---

`nock init` vendors nock into `.nock/core/` with the shim, `config.toml`, `tools/` and the primer `.nock/context.md`, and wires each agent harness it finds (Claude Code always; Codex, Cursor where their directory or command is): hooks, skills, the primer (CLAUDE.md imports it; AGENTS.md holds it), Claude Code's `permissions`. Run again, it re-wires. `nock upgrade` merges the latest release into the core (keeping local edits), then re-runs init. `nock-wiring` fails while it is stale.
