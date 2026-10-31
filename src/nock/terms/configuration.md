---
term: configuration
aliases: [config, settings, config-toml]
description: .nock/config.toml, committed; .nock/local/config.toml overrides it
---

`.nock/config.toml` is committed; `.nock/local/config.toml` overrides it on one machine; the `config` fixture reads both. Keys: `branch`, `reminders`, `output.*`, `run.deadline` and `silence`, `checks.*`, `reflect.*`, `agent.command`, `model` and `deadline`, `consult.enabled`, `deadline`, `upgrade.check`, `share`, `endpoints.*`, `environment.*`, `pricing`. The README's Settings table has each default.
