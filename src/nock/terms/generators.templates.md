---
term: generators.templates
aliases: [template, templates]
description: The template syntax of catalogs and briefs
---

A line starting with `!` is Python; a line ending with `:` opens a block, its lines indented four more spaces. Any other line is text, with `{{ expression }}` interpolated (`{{ value!r }}` for the repr); `\!` starts a text line with `!`. `include("name")` renders another template in place. A catalog's templates see `entries` (each with its `key`, fields as attributes), `catalog`, `catalogs` (every catalog's entries) and `tag`.
