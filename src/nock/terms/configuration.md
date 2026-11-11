---
term: configuration
aliases: [config, settings, config-toml]
description: .nock/config.toml, committed; .nock/local/config.toml overrides it
---

`.nock/config.toml` is committed; `.nock/local/config.toml` overrides it on one machine; the `config` fixture reads both. Keys: `branch`, `reminders`, `notifications`, `output.*`, `run.deadline` and `silence`, `checks.*`, `reflect.*`, `agent.command`, `model` and `deadline`, `permissions.confirm`, `studio.port`, `consult.enabled`, `deadline`, `upgrade.check`, `auto`, `share`, `endpoints.*`, `environment.*`, `pricing`. `.nock/nock docs guide.setup` has each default.
