---
term: generators
aliases: [generator, gen, generated, drift]
description: @nock.generator keeps a derived file in step with its source
---

`@nock.generator("src/version.py")` returns the file's text (given a final newline) or its exact bytes. `.nock/nock gen write` writes the files in the order they are defined, each before the next is generated, so one may read a file an earlier one writes. `.nock/nock check` fails when a generated file drifts. For a list that code is generated from: `.nock/nock docs generators.catalogs`.
