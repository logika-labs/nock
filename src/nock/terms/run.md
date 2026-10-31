---
term: run
aliases: [supervise, noisy, repeat]
description: nock run -- COMMAND: anything long or noisy, supervised and condensed
---

`.nock/nock run -- COMMAND` runs anything long or noisy under supervision: colors and redrawn progress bars dropped, repeated lines folded with a count, long output cut to its end with the log's path; it exits with the command's code. A failing call that repeats an earlier one byte for byte, with no file changed since, says so; it never refuses to run.
