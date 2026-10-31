---
term: checks.commands
aliases: [command-check, config-check]
description: A plain command as a check, in .nock/config.toml
---

`[checks.test]` with `command = "pytest -q"` in `.nock/config.toml`. Beside `command`: `fix` (a command that fixes what it finds, run first by `check --fix`), `chain`, `directory`, `deadline`, `silence`, and `failure_codes`, the exit codes that mean the code is wrong (`[1]`; any other means the machine).
