---
term: generators.catalogs
aliases: [catalog, catalogs]
description: A catalog: a list that code is generated from
---

A catalog (`.nock/nock gen new`; see its `--help`) is a list such as error codes, flags or strings, in `.nock/generators/NAME/`: `schema.json` (one entry), `entries.json`, `outputs.toml` (which template renders which file) and `templates/`. `.nock/nock gen add flags '{"key": "dark_mode", …}'` adds an entry and rewrites every bound file in one call; `gen set`, `rm`, `show`, `bind` and `unbind` likewise.
