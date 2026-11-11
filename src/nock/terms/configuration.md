---
term: configuration
aliases: [config, settings, config-toml]
description: Settings: the code's, the team's and one machine's; nock config
---

Three files, read in order: `.nock/config.toml` (the code's: `branch`, `run.*`, `checks.*`, `environment.*`, `permissions.confirm`, `upgrade.*`, `endpoints.*`; by hand), `.nock/shared/settings.toml` (the team's: `share`, `reminders`, `reflect.*`, `inbox.*`, `consult.enabled`, `agent.*`) and `.nock/local/config.toml` (one machine's: `notifications`, `studio.*`). `.nock/nock config [KEY [VALUE]]` lists, reads and sets the last two kinds.
