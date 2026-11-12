---
term: generators.catalogs
aliases: [catalog, catalogs]
description: A catalog: a list that code is generated from
---

A catalog is a list such as error codes, flags or strings, as plain files in `.nock/generators/NAME/`: `schema.json` (one entry's schema), `entries.json` (the entries by key), `outputs.toml` (`[[output]]` with `template` and `file`) and `templates/` (`docs generators.templates`). Edit the files; `.nock/nock gen` renders every bound file, refusing entries that don't fit the schema, and the `nock-generators` check fails on those and on drift.
